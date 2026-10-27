#!/usr/bin/env python3
"""Compute a SHA-256 checksum and basic metadata for a local artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


MANIFEST = "SHA256SUMS"


def write_manifest(folder: Path) -> tuple[Path, int]:
    """Пишет SHA256SUMS в формате sha256sum; проверка в папке: shasum -a 256 -c SHA256SUMS."""
    # Скрытые файлы (.DS_Store) ОС меняет сама, и они ломали бы проверку.
    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.name != MANIFEST and not p.name.startswith(".")
    )
    manifest = folder / MANIFEST
    manifest.write_text(
        "".join(f"{sha256_file(p)}  {p.relative_to(folder).as_posix()}\n" for p in files),
        encoding="utf-8",
    )
    return manifest, len(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Вычисляет SHA-256 локального артефакта.")
    parser.add_argument("path", help="Путь к файлу или папке многофайлового артефакта (для папки пишется SHA256SUMS)")
    parser.add_argument("--json", action="store_true", help="Вывести JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"Ошибка: файл не найден: {path}", file=sys.stderr)
        return 2
    if path.is_dir():
        manifest, count = write_manifest(path)
        result = {
            "path": str(path),
            "manifest": str(manifest),
            "files": count,
            "sha256": sha256_file(manifest),
        }
    elif not path.is_file():
        print(f"Ошибка: путь не является файлом или папкой: {path}", file=sys.stderr)
        return 2
    else:
        stat = path.stat()
        result = {
            "path": str(path),
            "filename": path.name,
            "size_bytes": stat.st_size,
            "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "sha256": sha256_file(path),
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
