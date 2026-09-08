#!/usr/bin/env python3
"""Create a secret-safe release manifest and ZIP with one top-level folder."""

import hashlib
import re
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/"BYBIT_5m_Crypto_Scanner_V2_6_SIGNAL_CORE_RC1.zip"
MANIFEST=ROOT/"BUILD_MANIFEST.txt"


def excluded(path):
    rel=path.relative_to(ROOT)
    parts=set(rel.parts)
    name=path.name
    return (
        name==".env" or name.startswith(".env.backup.") or
        ".venv" in parts or "__pycache__" in parts or
        name.endswith((".pyc",".pyo",".db",".db-wal",".db-shm",".zip")) or
        (rel.parts and rel.parts[0]=="data")
    )


def files(include_manifest=True):
    rows=[]
    for path in ROOT.rglob("*"):
        if not path.is_file() or excluded(path):continue
        if not include_manifest and path==MANIFEST:continue
        rows.append(path)
    return sorted(rows,key=lambda p:p.relative_to(ROOT).as_posix())


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def secret_scan(paths):
    forbidden=(b"discord.com/api/"+b"webhooks/",b"discordapp.com/api/"+b"webhooks/")
    token_pattern=re.compile(rb"[A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{6,8}\.[A-Za-z0-9_-]{25,45}")
    bad=[]
    for path in paths:
        data=path.read_bytes()
        if any(value in data for value in forbidden) or token_pattern.search(data):bad.append(path)
    if bad:
        raise RuntimeError("possible embedded Discord secret: "+", ".join(str(x) for x in bad))


def main():
    source=files(include_manifest=False)
    secret_scan(source)
    lines=[
        "Bybit 5m Crypto Scanner V2.6 SIGNAL CORE RC1",
        f"V2.6 strategy SHA-256: {sha(ROOT/'strategy.py')}",
        "Frozen V2.5 analyze AST SHA-256: 1458d94812ff37f2ee1b6279553c15f26bda57f29ae959c792174b4c2198a11b",
        "BUILD_MANIFEST.txt intentionally does not hash itself.",
        "",
    ]
    lines.extend(f"{sha(path)}  {path.stat().st_size:>8}  {path.relative_to(ROOT).as_posix()}" for path in source)
    MANIFEST.write_text("\n".join(lines)+"\n",encoding="utf-8")

    packaged=files(include_manifest=True)
    if OUT.exists():OUT.unlink()
    with zipfile.ZipFile(OUT,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in packaged:
            archive.write(path,(Path(ROOT.name)/path.relative_to(ROOT)).as_posix())
    with zipfile.ZipFile(OUT) as archive:
        names=archive.namelist()
        def unsafe(name):
            parts=Path(name).parts;leaf=parts[-1] if parts else ""
            return (leaf==".env" or leaf.startswith(".env.backup.") or
                    "__pycache__" in parts or name.endswith(".pyc"))
        if any(unsafe(name) for name in names):
            raise RuntimeError("release archive contains an excluded file")
    print(f"RC1: {OUT}")
    print(f"FILES: {len(packaged)}")
    print(f"SHA256: {sha(OUT)}")


if __name__=="__main__":main()
