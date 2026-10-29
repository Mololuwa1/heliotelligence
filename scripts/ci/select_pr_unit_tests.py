"""Conservative PR unit-test impact selection using only the standard library.

Analyze the checked-out tree (normally GitHub's PR merge checkout), without
importing application/test code. Main never uses this selector to narrow tests.
Deleted Python paths, unresolved internal imports and analysis failures fall
back to full. Opaque dynamic import consumers are added to otherwise classifiable selections;
this deliberately overselects rather than guessing their runtime targets.
They do not justify targeting a changed source with no identifiable tests.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

CI_SELECTOR_TEST = "tests/unit/test_ci/test_pr_unit_test_selector.py"
_ROOTS = ("src/heliotelligence", "tests/unit", "scripts")
_INTERNAL = frozenset({"heliotelligence", "tests", "scripts"})
_BROAD_PREFIXES = (
    "config/",
    "migrations/",
    "data_migration/",
    "tests/fixtures/",
    "src/heliotelligence/config/",
    "src/heliotelligence/db/",
    "src/heliotelligence/models/",
    "src/heliotelligence/data/",
)
_BROAD_FILES = frozenset(
    {
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "pdm.lock",
        "alembic.ini",
        "tests/__init__.py",
        "tests/unit/__init__.py",
        "src/heliotelligence/__init__.py",
    }
)


@dataclass(frozen=True)
class Selection:
    mode: Literal["skip", "targeted", "full"]
    reason: str
    changed_file_count: int
    tests: tuple[str, ...] = ()


class AnalysisError(ValueError):
    """The import graph cannot safely bound backend impact."""


def _is_test(path: str) -> bool:
    return (
        path.startswith("tests/unit/")
        and PurePosixPath(path).name.startswith("test_")
        and path.endswith(".py")
    )


def _safe_skip(path: str) -> bool:
    return path.startswith(("docs/", "frontend/")) or (
        len(PurePosixPath(path).parts) == 1 and path.lower().endswith(".md")
    )


def _ci_path(path: str) -> bool:
    return path.startswith((".github/workflows/", "scripts/ci/", "tests/unit/test_ci/"))


def _module(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[0] == "src":
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _ancestors(module: str) -> Iterable[str]:
    parts = module.split(".")
    return (".".join(parts[:i]) for i in range(1, len(parts) + 1))


@dataclass
class ImportGraph:
    modules: dict[str, str]
    dependencies: dict[str, set[str]]
    opaque_consumers: set[str]

    def affected_tests(self, module: str) -> set[str]:
        reverse: dict[str, set[str]] = defaultdict(set)
        for consumer, dependencies in self.dependencies.items():
            for dependency in dependencies:
                reverse[dependency].add(consumer)
        pending = deque([module])
        visited = {module}
        while pending:
            for consumer in reverse[pending.popleft()]:
                if consumer not in visited:
                    visited.add(consumer)
                    pending.append(consumer)
        return {self.modules[name] for name in visited if _is_test(self.modules[name])}


def build_import_graph(root: Path) -> ImportGraph:
    files = {path for folder in _ROOTS for path in (root / folder).rglob("*.py")}
    for relative in ("tests/__init__.py", "tests/conftest.py", "conftest.py"):
        ancestor = root / relative
        if ancestor.exists():
            files.add(ancestor)
    modules: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    packages: set[str] = set()
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise AnalysisError(f"symlinked Python module: {relative}")
        name = _module(relative)
        if name in modules:
            raise AnalysisError(f"ambiguous module identity: {name}")
        modules[name] = relative
        packages.update(_ancestors(name))
        try:
            trees[name] = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as error:
            raise AnalysisError(f"cannot parse {relative}: {error}") from error
    dependencies: dict[str, set[str]] = {name: set() for name in modules}
    opaque_consumers: set[str] = set()

    def resolve(consumer: str, target: str) -> None:
        if target.split(".")[0] not in _INTERNAL:
            return  # External/stdlib imports cannot be changed by this source diff.
        if target not in packages:
            raise AnalysisError(f"unresolved internal import in {modules[consumer]}: {target}")
        dependencies[consumer].update(name for name in _ancestors(target) if name in modules)

    by_path = {path: name for name, path in modules.items()}
    for name, tree in trees.items():
        # Pytest loads ancestor conftest modules implicitly, without a test's
        # import statement. Their transitive fixture/plugin imports count too.
        if _is_test(modules[name]):
            for parent in PurePosixPath(modules[name]).parents:
                conftest = by_path.get((parent / "conftest.py").as_posix())
                if conftest is not None:
                    dependencies[name].add(conftest)
        # Python initializes ancestor packages even for import package.child.
        dependencies[name].update(
            parent for parent in _ancestors(name) if parent in modules and parent != name
        )
        package = name if modules[name].endswith("/__init__.py") else name.rpartition(".")[0]
        import_functions = {"__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"importlib", "builtins"}:
                import_functions.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name in {"import_module", "__import__"}
                )
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(
                    isinstance(target, ast.Name) and target.id == "pytest_plugins"
                    for target in targets
                ):
                    try:
                        plugins = ast.literal_eval(node.value) if node.value is not None else ()
                    except (ValueError, TypeError, SyntaxError) as error:
                        raise AnalysisError(
                            f"computed pytest plugin configuration: {modules[name]}"
                        ) from error
                    if isinstance(plugins, str):
                        plugins = [plugins]
                    if not isinstance(plugins, (list, tuple)) or any(
                        not isinstance(plugin, str) for plugin in plugins
                    ):
                        raise AnalysisError(f"unknown pytest plugin configuration: {modules[name]}")
                    for plugin in plugins:
                        resolve(name, plugin)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolve(name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    parts = package.split(".") if package else []
                    if node.level > len(parts):
                        raise AnalysisError(f"relative import escapes package: {modules[name]}")
                    prefix = ".".join(
                        parts[: len(parts) - node.level + 1] + ([prefix] if prefix else [])
                    )
                resolve(name, prefix)
                for alias in node.names:
                    child = f"{prefix}.{alias.name}"
                    if alias.name == "*" and prefix.split(".")[0] in _INTERNAL:
                        dependencies[name].update(
                            mod for mod in modules if mod == prefix or mod.startswith(prefix + ".")
                        )
                    elif child in packages:
                        resolve(name, child)
            elif isinstance(node, ast.Call):
                function = node.func
                dynamic_import = (
                    isinstance(function, ast.Attribute) and function.attr == "import_module"
                ) or (isinstance(function, ast.Name) and function.id in import_functions)
                opaque_loader = (
                    isinstance(function, ast.Attribute)
                    and function.attr
                    in {"spec_from_file_location", "exec_module", "run_path", "run_module"}
                ) or (isinstance(function, ast.Name) and function.id in {"exec", "eval"})
                if dynamic_import:
                    literal = node.args[0] if node.args else None
                    if (
                        isinstance(literal, ast.Constant)
                        and isinstance(literal.value, str)
                        and not literal.value.startswith(".")
                        and len(node.args) == 1
                        and not node.keywords
                    ):
                        resolve(name, literal.value)
                    else:
                        # A computed/relative dynamic target can be any internal
                        # module. Include this consumer and every importer of it.
                        opaque_consumers.add(name)
                elif opaque_loader:
                    opaque_consumers.add(name)
    return ImportGraph(modules, dependencies, opaque_consumers)


def select_tests(root: Path, changed_files: Sequence[str]) -> Selection:
    changed = sorted(set(changed_files))
    count = len(changed)
    python_changes: list[str] = []
    infrastructure = False
    for path in changed:
        pure = PurePosixPath(path)
        if not path or pure.is_absolute() or ".." in pure.parts or "\x00" in path:
            return Selection("full", "invalid changed-file identity", count)
        if _safe_skip(path):
            continue
        if (
            path in _BROAD_FILES
            or pure.name == "conftest.py"
            or path.startswith(_BROAD_PREFIXES)
            or pure.name.startswith("requirements")
            or path.endswith(".lock")
        ):
            return Selection("full", f"broad backend/dependency configuration: {path}", count)
        if _ci_path(path):
            infrastructure = True
        elif not (
            path.endswith(".py") and path.startswith(("src/heliotelligence/", "tests/unit/"))
        ):
            return Selection("full", f"unclassified backend-affecting change: {path}", count)
        if path.endswith(".py"):
            if not (root / path).is_file():
                return Selection("full", f"deleted/unavailable Python module: {path}", count)
            python_changes.append(path)
    if not python_changes and not infrastructure:
        return Selection("skip", "no backend-affecting changes", count)
    try:
        graph = build_import_graph(root)
        selected: set[str] = set()
        if infrastructure:
            if not (root / CI_SELECTOR_TEST).is_file():
                raise AnalysisError("CI selector tests are unavailable")
            selected.add(CI_SELECTOR_TEST)
        for path in python_changes:
            name = _module(path)
            if graph.modules.get(name) != path:
                raise AnalysisError(f"changed module is outside analyzed graph: {path}")
            affected = graph.affected_tests(name)
            if _is_test(path):
                affected.add(path)
            if path.startswith("src/heliotelligence/"):
                relative = PurePosixPath(path).relative_to("src/heliotelligence")
                mirrored = PurePosixPath(
                    "tests/unit",
                    *("test_" + part for part in relative.parts[:-1]),
                    "test_" + relative.name,
                ).as_posix()
                if (root / mirrored).is_file():
                    affected.add(mirrored)
            if not affected:
                raise AnalysisError(f"no affected unit tests identified for {path}")
            selected.update(affected)
        if not selected:
            raise AnalysisError("no unit tests safely identified")
        if python_changes:
            for consumer in graph.opaque_consumers:
                selected.update(graph.affected_tests(consumer))
        return Selection(
            "targeted",
            "changed tests and transitive internal import consumers",
            count,
            tuple(sorted(selected)),
        )
    except (AnalysisError, OSError, UnicodeError) as error:
        return Selection("full", str(error), count)


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    if not all(re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", sha) for sha in (base, head)):
        raise AnalysisError("base/head must be explicit commit SHAs")
    # Disable rename compression so removed modules cannot lose their old path.
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", "--no-renames", base, head, "--"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [name for name in result.stdout.decode("utf-8").split("\x00") if name]


def publish(selection: Selection, github_output: Path | None) -> None:
    print("PR backend test selection:")
    print(f"mode: {selection.mode}")
    print(f"reason: {selection.reason}")
    print(f"changed files: {selection.changed_file_count}")
    print(f"selected test files: {len(selection.tests)}")
    for path in selection.tests:
        print(f"  {path}")
    if github_output is not None:
        # JSON is a single output line, then decoded into an argv list by CI.
        # Filenames are never interpolated into shell commands.
        with github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"mode={selection.mode}\n")
            stream.write(f"tests={json.dumps(selection.tests, ensure_ascii=True)}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--github-output", type=Path)
    arguments = parser.parse_args(argv)
    root = Path.cwd()
    try:
        paths = changed_paths(root, arguments.base, arguments.head)
        selection = select_tests(root, paths)
    except Exception as error:  # Any operational/analysis uncertainty must fail safe.
        selection = Selection("full", f"cannot safely select PR tests: {error}", 0)
    publish(selection, arguments.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
