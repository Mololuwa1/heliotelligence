#!/usr/bin/env python3
"""Run bounded PVCollada acceptance checks against a private local artifact."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from heliotelligence.ingest.pvcollada import (
    AcceptanceCheck,
    AcceptanceStatus,
    PVColladaAcceptanceReport,
    PVColladaImportError,
    acceptance_report_dict,
    evaluate_pvcollada_acceptance,
    import_pvcollada_2,
    parse_acceptance_expectations,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the private acceptance command and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--geometry-revision", required=True)
    parser.add_argument("--expectations", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--supplied-as")
    parser.add_argument(
        "--verify-determinism",
        action="store_true",
        help="repeat the import and require identical canonical output and diagnostics",
    )
    args = parser.parse_args(argv)
    input_label = args.input.name
    if args.report is not None:
        try:
            collision = _same_file(args.report, args.input) or _same_file(
                args.report, args.expectations
            )
        except (OSError, RuntimeError):
            _write_error("unable to validate acceptance report destination")
            return 2
        if collision:
            _write_error("acceptance report destination conflicts with a private input")
            return 2
    try:
        source = args.input.read_bytes()
        expectations = parse_acceptance_expectations(args.expectations.read_bytes())
        imported = import_pvcollada_2(source, geometry_revision=args.geometry_revision)
        report = evaluate_pvcollada_acceptance(imported, expectations)
        if args.verify_determinism:
            repeated = import_pvcollada_2(source, geometry_revision=args.geometry_revision)
            passed = repeated == imported
            check = AcceptanceCheck(
                name="deterministic_repeat_import",
                status=AcceptanceStatus.PASS if passed else AcceptanceStatus.FAIL,
                expected="equal",
                actual="equal" if passed else "different",
                message="repeat import matched" if passed else "repeat import differed",
            )
            checks = report.checks + (check,)
            report = PVColladaAcceptanceReport(
                status=(
                    AcceptanceStatus.PASS
                    if all(item.status is AcceptanceStatus.PASS for item in checks)
                    else AcceptanceStatus.FAIL
                ),
                summary=report.summary,
                checks=checks,
            )
        payload = acceptance_report_dict(
            report,
            expectations,
            input_label=input_label,
            supplied_as=args.supplied_as,
        )
    except (OSError, PVColladaImportError, ValueError) as exc:
        payload = {
            "status": AcceptanceStatus.FAIL.value,
            "input_label": input_label,
            "error": _bounded_error(exc),
        }
        if not _emit_safely(payload, args.report):
            return 2
        return 2
    if not _emit_safely(payload, args.report):
        return 2
    return 0 if report.status is AcceptanceStatus.PASS else 1


def _same_file(left: Path, right: Path) -> bool:
    """Detect textual, resolved, symlink, and existing hard-link aliases."""
    if left.resolve(strict=False) == right.resolve(strict=False):
        return True
    if left.exists() and right.exists():
        return os.path.samefile(left, right)
    return False


def _bounded_error(error: Exception) -> str:
    """Return a concise error without private paths or input content."""
    if isinstance(error, OSError):
        return "unable to read or write a requested local file"
    if isinstance(error, PVColladaImportError):
        return f"PVCollada import failed ({type(error).__name__})"
    return " ".join(str(error).split())[:500]


def _emit(payload: dict[str, object], report_path: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if report_path is None:
        sys.stdout.write(text)
    else:
        report_path.write_text(text, encoding="utf-8")


def _emit_safely(payload: dict[str, object], report_path: Path | None) -> bool:
    try:
        _emit(payload, report_path)
    except OSError:
        _write_error("unable to write acceptance report")
        return False
    return True


def _write_error(message: str) -> None:
    with suppress(OSError):
        sys.stderr.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
