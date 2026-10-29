"""Impact selection against synthetic trees; no application imports or test execution."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ci import select_pr_unit_tests as selector


def write(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def basic(root: Path) -> Path:
    return write(
        root,
        {
            "src/heliotelligence/__init__.py": "",
            "src/heliotelligence/feature.py": "value = 1\n",
            "tests/unit/test_feature.py": "from heliotelligence.feature import value\n",
        },
    )


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/architecture.md"],
        ["README.md", "CHANGELOG.md"],
        ["frontend/src/app.tsx", "frontend/package-lock.json"],
        ["docs/a.md", "frontend/src/main.ts", "README.md"],
        [],
    ],
)
def test_clearly_non_backend_changes_skip(tmp_path: Path, paths: list[str]) -> None:
    result = selector.select_tests(tmp_path, paths)
    assert result.mode == "skip"
    assert result.reason == "no backend-affecting changes"
    assert result.tests == ()


def test_changed_test_is_always_included(tmp_path: Path) -> None:
    write(tmp_path, {"tests/unit/test_direct.py": "def test_case(): pass\n"})
    result = selector.select_tests(tmp_path, ["tests/unit/test_direct.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_direct.py",)


@pytest.mark.parametrize(
    "statement",
    [
        "import heliotelligence.feature",
        "import heliotelligence.feature as feature",
        "from heliotelligence.feature import value",
        "from heliotelligence import feature",
    ],
)
def test_direct_source_import_forms(tmp_path: Path, statement: str) -> None:
    basic(tmp_path)
    write(tmp_path, {"tests/unit/test_feature.py": statement + "\n"})
    result = selector.select_tests(
        tmp_path, ["src/heliotelligence/feature.py", "tests/unit/test_feature.py"]
    )
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_feature.py",)


def test_test_helper_transitively_imports_changed_source(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/changed.py": "value = 1\n",
            "src/heliotelligence/bridge.py": "from .changed import value\n",
            "tests/unit/helpers.py": "from heliotelligence.bridge import value\n",
            "tests/unit/test_a.py": "from tests.unit.helpers import value\n",
            "tests/unit/test_b.py": "from tests.unit import test_a\n",
            "tests/unit/test_other.py": "import math\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/changed.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_a.py", "tests/unit/test_b.py")


def test_changed_helper_selects_transitive_consumers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "tests/unit/group/__init__.py": "",
            "tests/unit/group/helper.py": "value = 1\n",
            "tests/unit/group/bridge.py": "from .helper import value\n",
            "tests/unit/group/test_a.py": "from .bridge import value\n",
            "tests/unit/test_b.py": "from tests.unit.group.test_a import value\n",
        },
    )
    result = selector.select_tests(tmp_path, ["tests/unit/group/helper.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/group/test_a.py", "tests/unit/test_b.py")


def test_package_reexports_and_ancestor_initializers(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/feature/__init__.py": "from .implementation import value\n",
            "src/heliotelligence/feature/implementation.py": "value = 1\n",
            "src/heliotelligence/feature/extra.py": "other = 2\n",
            "tests/unit/test_api.py": "from heliotelligence.feature import value\n",
            "tests/unit/test_extra.py": "import heliotelligence.feature.extra\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature/implementation.py"])
    assert result.tests == ("tests/unit/test_api.py", "tests/unit/test_extra.py")


def test_relative_parent_import(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/core.py": "value = 1\n",
            "src/heliotelligence/nested/wrapper.py": "from ..core import value\n",
            "tests/unit/test_consumer.py": "from heliotelligence.nested.wrapper import value\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/core.py"])
    assert result.tests == ("tests/unit/test_consumer.py",)


def test_cyclic_imports_terminate_and_selection_is_sorted_unique(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/a.py": "from . import b\n",
            "src/heliotelligence/b.py": "from . import a\n",
            "tests/unit/test_z.py": "from heliotelligence import b\n",
            "tests/unit/test_a.py": "from heliotelligence import a, b\n",
        },
    )
    paths = ["src/heliotelligence/b.py", "tests/unit/test_z.py", "src/heliotelligence/a.py"]
    first = selector.select_tests(tmp_path, paths)
    second = selector.select_tests(tmp_path, list(reversed(paths)) + paths)
    assert first == second
    assert first.tests == ("tests/unit/test_a.py", "tests/unit/test_z.py")


def test_filename_mirror_is_supplemental(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/physics/item.py": "value = 1\n",
            "tests/unit/test_physics/test_item.py": "def test_something(): pass\n",
            "tests/unit/test_transitive.py": "from heliotelligence.physics.item import value\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/physics/item.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_physics/test_item.py", "tests/unit/test_transitive.py")


@pytest.mark.parametrize(
    "path",
    [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.in",
        "uv.lock",
        "poetry.lock",
        "pytest.ini",
        "setup.cfg",
        "tests/conftest.py",
        "tests/unit/conftest.py",
        "tests/unit/test_group/conftest.py",
        "config/sites.yaml",
        "tests/fixtures/input.csv",
        "migrations/versions/0008_change.py",
        "data_migration/copy.py",
        "alembic.ini",
        "src/heliotelligence/data/library.yaml",
        "src/heliotelligence/config/site.py",
        "src/heliotelligence/db/session.py",
        "src/heliotelligence/models/expected_energy.py",
        "src/heliotelligence/__init__.py",
        "tests/unit/__init__.py",
        "Dockerfile",
        ".env.example",
        "src/heliotelligence/templates/report.html",
        "tests/integration/test_api.py",
    ],
)
def test_broad_or_unclassified_backend_impact_is_full(tmp_path: Path, path: str) -> None:
    result = selector.select_tests(tmp_path, ["docs/a.md", path])
    assert result.mode == "full"
    assert path in result.reason


def test_orphan_source_is_full_even_if_another_source_has_tests(tmp_path: Path) -> None:
    basic(tmp_path)
    write(tmp_path, {"src/heliotelligence/orphan.py": "value = 1\n"})
    result = selector.select_tests(
        tmp_path, ["src/heliotelligence/feature.py", "src/heliotelligence/orphan.py"]
    )
    assert result.mode == "full"
    assert "no affected unit tests" in result.reason


@pytest.mark.parametrize(
    "source", ["def broken(:", "import heliotelligence.missing", "from ...missing import value"]
)
def test_parse_and_internal_import_failures_are_full(tmp_path: Path, source: str) -> None:
    basic(tmp_path)
    write(tmp_path, {"src/heliotelligence/broken.py": source})
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.mode == "full"
    assert any(word in result.reason for word in ["parse", "import"])


def test_deleted_or_renamed_python_path_is_full(tmp_path: Path) -> None:
    basic(tmp_path)
    assert selector.select_tests(tmp_path, ["src/heliotelligence/old.py"]).mode == "full"
    assert selector.select_tests(tmp_path, ["tests/unit/test_removed.py"]).mode == "full"


@pytest.mark.parametrize(
    "statement",
    [
        'import importlib\nsupport = importlib.import_module("heliotelligence.feature")',
        'from importlib import import_module as load\nsupport = load("heliotelligence.feature")',
        'support = __import__("heliotelligence.feature")',
        'from builtins import __import__ as load\nsupport = load("heliotelligence.feature")',
    ],
)
def test_literal_dynamic_imports_are_traced(tmp_path: Path, statement: str) -> None:
    basic(tmp_path)
    (tmp_path / "tests/unit/test_feature.py").unlink()
    write(tmp_path, {"tests/unit/test_dynamic.py": statement})
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_dynamic.py",)


def test_opaque_import_consumers_are_added_conservatively(tmp_path: Path) -> None:
    basic(tmp_path)
    write(
        tmp_path,
        {
            "tests/unit/dynamic_helper.py": (
                "import importlib\nmodule = importlib.import_module(runtime_name)\n"
            ),
            "tests/unit/test_opaque.py": "from tests.unit import dynamic_helper\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.tests == ("tests/unit/test_feature.py", "tests/unit/test_opaque.py")
    write(tmp_path, {"src/heliotelligence/orphan.py": "value = 2\n"})
    assert selector.select_tests(tmp_path, ["src/heliotelligence/orphan.py"]).mode == "full"


def test_infrastructure_selects_its_own_tests(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "scripts/ci/select_pr_unit_tests.py": "value = 1\n",
            selector.CI_SELECTOR_TEST: "from scripts.ci import select_pr_unit_tests\n",
            "tests/unit/test_ci/__init__.py": "",
        },
    )
    result = selector.select_tests(
        tmp_path,
        [
            ".github/workflows/ci.yml",
            "scripts/ci/select_pr_unit_tests.py",
            "tests/unit/test_ci/__init__.py",
            selector.CI_SELECTOR_TEST,
        ],
    )
    assert result.mode == "targeted"
    assert result.tests == (selector.CI_SELECTOR_TEST,)
    assert selector.select_tests(tmp_path, [".github/workflows/other.yml"]).tests == (
        selector.CI_SELECTOR_TEST,
    )


def test_workflow_change_without_available_selector_tests_is_full(tmp_path: Path) -> None:
    result = selector.select_tests(tmp_path, [".github/workflows/ci.yml"])
    assert result.mode == "full"
    assert "CI selector tests" in result.reason


def test_s14b_shaped_change_emerges_from_generic_dependencies(tmp_path: Path) -> None:
    files = {
        "src/heliotelligence/physics/revenue_meter_interval_support_policy.py": "value = 1\n",
        "src/heliotelligence/physics/revenue_meter_interval_benchmark.py": (
            "from .revenue_meter_interval_support_policy import value\n"
        ),
        "src/heliotelligence/physics/revenue_meter_loss_attribution.py": (
            "from .revenue_meter_interval_benchmark import value\n"
        ),
        "tests/unit/test_physics/test_revenue_meter_interval_support_policy.py": (
            "from heliotelligence.physics.revenue_meter_interval_support_policy import value\n"
        ),
        "tests/unit/test_physics/test_revenue_meter_interval_benchmark.py": (
            "from heliotelligence.physics.revenue_meter_interval_benchmark import value\n"
        ),
        "tests/unit/test_physics/test_revenue_meter_loss_attribution.py": (
            "from heliotelligence.physics.revenue_meter_loss_attribution import value\n"
        ),
        "tests/unit/test_unrelated.py": "def test_other(): pass\n",
    }
    write(tmp_path, files)
    changes = [
        name
        for name in files
        if "revenue_meter" in name
        and "src/heliotelligence/physics/revenue_meter_loss_attribution" not in name
    ]
    result = selector.select_tests(tmp_path, changes + ["docs/a.md"])
    assert result.mode == "targeted"
    assert result.tests == tuple(
        sorted(name for name in files if name.startswith("tests/unit/test_physics/"))
    )


@pytest.mark.parametrize("path", ["/tmp/test.py", "../test.py", "", "tests/unit/../test.py"])
def test_invalid_diff_paths_cannot_silently_skip(tmp_path: Path, path: str) -> None:
    assert selector.select_tests(tmp_path, [path]).mode == "full"


def test_json_output_preserves_filenames_without_shell_splitting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names = (
        "tests/unit/test_a space.py",
        'tests/unit/test_a"quote.py',
        "tests/unit/test_new\nline.py",
    )
    selected = selector.Selection("targeted", "explicit test", 3, names)
    output = tmp_path / "github-output"
    selector.publish(selected, output)
    lines = output.read_text().splitlines()
    assert lines[0] == "mode=targeted"
    assert json.loads(lines[1].removeprefix("tests=")) == list(names)
    assert len(lines) == 2
    summary = capsys.readouterr().out
    assert (
        "mode: targeted" in summary
        and "changed files: 3" in summary
        and "selected test files: 3" in summary
    )


def git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_git_diff_cli_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    basic(tmp_path)
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "ci-test@example.invalid")
    git(tmp_path, "config", "user.name", "CI test")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    base = git(tmp_path, "rev-parse", "HEAD")
    write(tmp_path, {"src/heliotelligence/feature.py": "value = 2\n"})
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "head")
    head = git(tmp_path, "rev-parse", "HEAD")
    assert selector.changed_paths(tmp_path, base, head) == ["src/heliotelligence/feature.py"]
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "github-output"
    assert selector.main(["--base", base, "--head", head, "--github-output", str(output)]) == 0
    lines = output.read_text().splitlines()
    assert lines[0] == "mode=targeted"
    assert json.loads(lines[1].removeprefix("tests=")) == ["tests/unit/test_feature.py"]
    output.unlink()
    assert selector.main(["--base", "0" * 40, "--head", head, "--github-output", str(output)]) == 0
    assert output.read_text().splitlines()[0] == "mode=full"
    git(tmp_path, "mv", "src/heliotelligence/feature.py", "src/heliotelligence/renamed.py")
    git(tmp_path, "commit", "-m", "rename")
    renamed_head = git(tmp_path, "rev-parse", "HEAD")
    renamed_paths = selector.changed_paths(tmp_path, head, renamed_head)
    assert set(renamed_paths) == {
        "src/heliotelligence/feature.py",
        "src/heliotelligence/renamed.py",
    }
    assert selector.select_tests(tmp_path, renamed_paths).mode == "full"


def test_selector_imports_only_standard_library() -> None:
    tree = ast.parse(Path(selector.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert all(
            name.split(".")[0] in sys.stdlib_module_names or name == "__future__" for name in names
        )


def test_implicit_conftest_helper_dependency_selects_entire_scope(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "tests/unit/helpers.py": "value = 1\n",
            "tests/unit/group/conftest.py": "from tests.unit.helpers import value\n",
            "tests/unit/group/test_a.py": "def test_a(): pass\n",
            "tests/unit/group/nested/test_b.py": "def test_b(): pass\n",
            "tests/unit/test_outside.py": "def test_c(): pass\n",
        },
    )
    result = selector.select_tests(tmp_path, ["tests/unit/helpers.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/group/nested/test_b.py", "tests/unit/group/test_a.py")


def test_global_conftest_and_literal_plugin_dependencies(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "src/heliotelligence/feature.py": "value = 1\n",
            "tests/plugin.py": "",  # Outside the unit graph is not assumed traceable.
            "tests/unit/plugin.py": "from heliotelligence.feature import value\n",
            "tests/conftest.py": 'pytest_plugins = ["tests.unit.plugin"]\n',
            "tests/unit/test_a.py": "def test_a(): pass\n",
            "tests/unit/test_b.py": "def test_b(): pass\n",
        },
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_a.py", "tests/unit/test_b.py")


def test_computed_plugin_configuration_is_full(tmp_path: Path) -> None:
    basic(tmp_path)
    write(tmp_path, {"tests/conftest.py": "pytest_plugins = compute_plugins()\n"})
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.mode == "full"
    assert "computed pytest plugin" in result.reason


def test_dynamic_import_with_relative_level_is_conservative(tmp_path: Path) -> None:
    basic(tmp_path)
    write(
        tmp_path,
        {"tests/unit/test_relative_loader.py": 'module = __import__("feature", level=1)\n'},
    )
    result = selector.select_tests(tmp_path, ["src/heliotelligence/feature.py"])
    assert result.mode == "targeted"
    assert result.tests == ("tests/unit/test_feature.py", "tests/unit/test_relative_loader.py")
