"""Import direction for chanedge packages. Extra internal imports fail this test."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "chanedge"

ALLOWED: dict[str, set[str]] = {
    "domain": set(),
    "config": {"domain"},
    "marketdata": {"domain", "config"},
    "chanlun": {"domain"},
    "features": {"domain"},
    "jev": {"domain"},
    "rules": {"domain"},
    "risk": {"domain"},
    "execution": {"domain"},
    "journal": {"domain"},
    "backtest": {"domain"},
    "monitor": {"domain", "journal"},
    "typesafe": {"domain"},
    "app": {
        "domain",
        "config",
        "marketdata",
        "chanlun",
        "features",
        "jev",
        "rules",
        "risk",
        "execution",
        "backtest",
        "journal",
        "monitor",
        "typesafe",
    },
}


def internal_imports(source: str, package: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _absolute_package(alias.name)
                if target is not None:
                    found.add(target)
        elif isinstance(node, ast.ImportFrom):
            target = _from_import(package, node)
            if target is not None:
                found.add(target)
    if package:
        found.discard(package)
    return found


def _absolute_package(module: str) -> str | None:
    parts = module.split(".")
    if not parts or parts[0] != "chanedge" or len(parts) < 2:
        return None
    return parts[1]


def _from_import(package: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        if node.module is None:
            return None
        return _absolute_package(node.module)
    parts = package.split(".") if package else []
    keep = len(parts) - (node.level - 1)
    if keep < 0:
        return None
    base = parts[:keep]
    if node.module:
        base.extend(node.module.split("."))
    if not base:
        return None
    return base[0]


def test_scanner_flags_execution_importing_journal() -> None:
    found = internal_imports("from chanedge.journal import ledger\n", "execution")
    assert found == {"journal"}
    assert not found <= ALLOWED["execution"]


def test_scanner_ignores_same_package_and_third_party() -> None:
    source = "from .model import Settings\nfrom pydantic import BaseModel\nimport yaml\n"
    assert internal_imports(source, "config") == set()


def test_package_imports_stay_inside_the_allow_table() -> None:
    seen: set[str] = set()
    for path in SRC.rglob("*.py"):
        package = _package_of(path)
        if package:
            seen.add(package)
            if package not in ALLOWED:
                raise AssertionError(f"{path} is not in the allow table")
        source = path.read_text(encoding="utf-8")
        found = internal_imports(source, package)
        allowed = ALLOWED.get(package, set())
        extra = found - allowed
        if extra:
            raise AssertionError(f"{path} imports {sorted(extra)}")
    missing = set(ALLOWED) - seen
    if missing:
        raise AssertionError(f"missing packages: {sorted(missing)}")


def test_pyproject_declares_phase1_stack_and_the_cli() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["requires-python"] == ">=3.12"
    assert project["scripts"]["chanedge"] == "chanedge.app.cli:main"
    deps = " ".join(project["dependencies"]).lower()
    for name in ("pydantic", "pyyaml", "pandas", "pyarrow", "sqlalchemy", "structlog", "ccxt"):
        assert name in deps
    for banned in ("czsc", "chan.py", "chanlun", "backtrader", "vectorbt", "polars", "duckdb"):
        assert banned not in deps


def test_typesafe_sdk_is_imported_only_by_the_adapter() -> None:
    for path in SRC.rglob("*.py"):
        if "typesafe_sdk" not in path.read_text(encoding="utf-8"):
            continue
        if "typesafe" not in path.relative_to(SRC).parts:
            raise AssertionError(path)


def _package_of(path: Path) -> str:
    parts = path.relative_to(SRC).parts
    if len(parts) == 1:
        return ""
    return parts[0]
