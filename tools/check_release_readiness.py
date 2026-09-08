#!/usr/bin/env python3
"""Fail closed on repository metadata or tracked-artifact release hazards."""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

COMPONENTS = {
    "Bybit Scanner V2.6": ROOT / "apps/scanner_v2_6/VERSION",
    "Bybit Demo AutoTrader": ROOT / "apps/autotrader/VERSION",
    "Bybit Scanner V2.5": ROOT / "legacy/scanner_v2_5/VERSION",
}

FORBIDDEN_EXACT_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "bridge_secret",
    "bridge_secret.txt",
}
FORBIDDEN_SUFFIXES = {
    ".db",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
FORBIDDEN_PATH_PARTS = {
    "credentials",
    "secrets",
    "trade_history",
}
FORBIDDEN_PATH_PREFIXES = (
    "data/private/",
    "data/raw/",
    "reports/private/",
    "trades/",
    "positions/",
    "orders/",
    "backtests/output/",
)


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_version(path: Path) -> str:
    if not path.is_file():
        fail(f"missing version file: {path.relative_to(ROOT)}")
    value = path.read_text(encoding="utf-8").strip()
    if not value or any(char.isspace() for char in value):
        fail(f"invalid version value in {path.relative_to(ROOT)}: {value!r}")
    return value


def package_source_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    fail("could not find a literal __version__ assignment in package __init__.py")


def tracked_files() -> list[str]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        fail(f"could not enumerate tracked files with git: {exc}")
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def artifact_hazard(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    lower_name = pure.name.lower()
    lower_parts = {part.lower() for part in pure.parts}
    lower_path = normalized.lower()

    if lower_name == ".env.example":
        return None
    if lower_name in FORBIDDEN_EXACT_NAMES:
        return "secret/runtime filename"
    if lower_name.startswith(".env."):
        return "environment backup/runtime file"
    if pure.suffix.lower() in FORBIDDEN_SUFFIXES:
        return f"forbidden runtime/secret suffix {pure.suffix.lower()}"
    if FORBIDDEN_PATH_PARTS.intersection(lower_parts):
        return "private secret/runtime directory"
    if any(lower_path.startswith(prefix) for prefix in FORBIDDEN_PATH_PREFIXES):
        return "private runtime-data path"
    return None


def check_root_package_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        metadata = tomllib.load(handle)
    project_version = str(metadata["project"]["version"])
    source_version = package_source_version(ROOT / "src/open_crypto_signal_engine/__init__.py")
    if project_version != source_version:
        fail(
            "root package version mismatch: "
            f"pyproject={project_version!r} package={source_version!r}"
        )
    return project_version


def check_component_versions() -> dict[str, str]:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    versions = {name: read_version(path) for name, path in COMPONENTS.items()}
    expected_rows = {
        "Bybit Scanner V2.6": (
            f"| [Bybit Scanner V2.6](apps/scanner_v2_6/) | `{versions['Bybit Scanner V2.6']}` |"
        ),
        "Bybit Demo AutoTrader": (
            f"| [Bybit Demo AutoTrader](apps/autotrader/) | `{versions['Bybit Demo AutoTrader']}` |"
        ),
        "Bybit Scanner V2.5": (
            f"| [Bybit Scanner V2.5](legacy/scanner_v2_5/) | `{versions['Bybit Scanner V2.5']}` |"
        ),
    }
    for name, expected in expected_rows.items():
        if expected not in readme:
            fail(f"README component table does not match {name} VERSION ({versions[name]})")
    return versions


def check_tracked_artifacts() -> int:
    files = tracked_files()
    hazards = [(path, reason) for path in files if (reason := artifact_hazard(path))]
    if hazards:
        lines = "\n".join(f"  - {path}: {reason}" for path, reason in hazards)
        fail(f"forbidden tracked release artifacts detected:\n{lines}")
    return len(files)


def main() -> int:
    package_version = check_root_package_version()
    component_versions = check_component_versions()
    tracked_count = check_tracked_artifacts()

    print("RELEASE READINESS METADATA PASSED")
    print(f"Root package: {package_version}")
    for name, version in component_versions.items():
        print(f"{name}: {version}")
    print(f"Tracked files checked: {tracked_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
