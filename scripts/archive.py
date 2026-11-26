#!/usr/bin/env python3
"""Deterministic zip helpers shared by build.py and patches.py."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path


def add_bytes(
    zf: zipfile.ZipFile,
    data: bytes,
    arcname: str,
    compress_type: int = zipfile.ZIP_DEFLATED,
) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compress_type
    info.create_system = 3  # fixed so local Windows builds match Linux CI
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def add_file(
    zf: zipfile.ZipFile,
    source: Path,
    arcname: str,
    compress_type: int = zipfile.ZIP_DEFLATED,
) -> None:
    add_bytes(zf, source.read_bytes(), arcname, compress_type)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
