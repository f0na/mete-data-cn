#!/usr/bin/env python3
"""Build additive resource patches between release versions.

Patches only contain assets added after the `from` version.  They never remove
or modify files, and they never contain `servant.json`: the data package is
always downloaded in full (it is under 1 MB).

Two patches are produced for every patch release:

    patch-<base>-000-<to>.zip          cumulative from the base
    patch-<base>-<from>-<to>.zip       adjacent to the previous patch

Both are plain zips of the new resource files; asset paths in the archive are
the same paths stored in servant.json.

Usage:
    python scripts/patches.py --version data-2026.11.27.001 --check
    python scripts/patches.py --version data-2026.11.27.001
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVANTS_DIR = ROOT / "servants"
DIST_DIR = ROOT / "dist"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive  # noqa: E402  (local helper module)
import assets  # noqa: E402  (local helper module)
import version as version_mod  # noqa: E402  (local helper module)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def patch_name(base: str, from_patch: int, to_patch: int, prefix: str = "") -> str:
    if prefix:
        return f"patch-{prefix}-{base}-{from_patch:03d}-{to_patch:03d}.zip"
    return f"patch-{base}-{from_patch:03d}-{to_patch:03d}.zip"


def patch_tag(base: str, patch: int) -> str:
    if patch == 0:
        return f"data-{base}"
    return f"data-{base}.{patch:03d}"


def collect_refs_from_dir(directory: Path = SERVANTS_DIR) -> set[str]:
    refs: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        assets.collect(data, [], refs)
    return refs


def collect_refs_from_tag(tag: str, directory: Path = SERVANTS_DIR) -> set[str]:
    """Return the asset paths referenced by a dataset directory at a git tag."""
    # A dataset introduced after the base tag has no path there yet; treat it
    # as empty so its first patch (or base) can still be built.
    exists = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{tag}:{directory.name}"],
        capture_output=True,
    )
    if exists.returncode != 0:
        return set()

    proc = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", tag, directory.name],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git archive failed for {tag}: {detail}")

    refs: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{tag}:{member.name}: invalid JSON ({exc})") from exc
            assets.collect(data, [], refs)
    return refs


def previous_patch(version: version_mod.Version) -> int:
    """Highest existing patch number below `version.patch` for the same base."""
    if version.patch <= 0:
        return 0
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "-l", f"data-{version.base}.*"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git tag failed")

    best = 0
    for tag in proc.stdout.split():
        candidate = version_mod.parse_tag(tag, strict=False)
        if candidate is None:
            continue
        if candidate.base == version.base and 0 < candidate.patch < version.patch:
            best = max(best, candidate.patch)
    return best


def build_patch_archive(
    path: Path,
    rels: set[str],
    assets_dir: Path,
) -> dict:
    ordered = sorted(rels)
    missing = [rel for rel in ordered if not (assets_dir / rel).is_file()]
    if missing:
        for rel in missing[:20]:
            print(f"  missing: {rel}", file=sys.stderr)
        raise RuntimeError(f"{len(missing)} patch asset(s) missing from {assets_dir}")

    with zipfile.ZipFile(path, "w") as zf:
        for rel in ordered:
            # PNGs are already compressed; keep the patch bytes identical to
            # the resource package entries.
            archive.add_file(zf, assets_dir / rel, rel, zipfile.ZIP_STORED)

    return {
        "archive": path.name,
        "bytes": path.stat().st_size,
        "sha256": archive.sha256_file(path),
    }


def build_patches(
    version: version_mod.Version,
    current_refs: set[str],
    assets_dir: Path,
    dist_dir: Path,
    directory: Path = SERVANTS_DIR,
    prefix: str = "",
) -> list[dict]:
    """Create cumulative and adjacent patch archives for a patch release."""
    if version.patch <= 0:
        return []

    base_refs = collect_refs_from_tag(version.base_tag, directory)
    prev_patch = previous_patch(version)
    prev_refs = (
        collect_refs_from_tag(patch_tag(version.base, prev_patch), directory)
        if prev_patch
        else base_refs
    )

    entries: list[dict] = []

    cumulative = current_refs - base_refs
    if cumulative:
        name = patch_name(version.base, 0, version.patch, prefix)
        info = build_patch_archive(dist_dir / name, cumulative, assets_dir)
        entries.append({"from": 0, "to": version.patch, **info})
        print(f"Built {name} ({len(cumulative)} new file(s))")
    else:
        # Publish an empty cumulative patch.  Without an entry the client
        # cannot tell "nothing changed" from "no patch available" and falls
        # back to downloading the full resource archive.
        name = patch_name(version.base, 0, version.patch, prefix)
        info = build_patch_archive(dist_dir / name, set(), assets_dir)
        entries.append({"from": 0, "to": version.patch, **info})
        print(f"Built {name} (no new files)")

    if prev_patch:
        adjacent = current_refs - prev_refs
        # If the previous patch added nothing, adjacent is identical to the
        # cumulative archive; publishing a second copy would be pure waste.
        if adjacent and adjacent != cumulative:
            name = patch_name(version.base, prev_patch, version.patch, prefix)
            info = build_patch_archive(dist_dir / name, adjacent, assets_dir)
            entries.append({"from": prev_patch, "to": version.patch, **info})
            print(f"Built {name} ({len(adjacent)} new file(s))")

    if not entries:
        print(f"no new assets since {version.base_tag}; no patch archives generated")
    return entries


def describe(
    version: version_mod.Version,
    current_refs: set[str],
    directory: Path = SERVANTS_DIR,
) -> tuple[int, int, int]:
    base_refs = collect_refs_from_tag(version.base_tag, directory)
    prev_patch = previous_patch(version)
    prev_refs = (
        collect_refs_from_tag(patch_tag(version.base, prev_patch), directory)
        if prev_patch
        else base_refs
    )
    return len(current_refs - base_refs), len(current_refs - prev_refs), prev_patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="release tag, e.g. data-2026.11.27.001")
    parser.add_argument("--dist", type=Path, default=DIST_DIR, help="output directory")
    parser.add_argument("--check", action="store_true", help="report counts without writing archives")
    args = parser.parse_args()

    try:
        version = version_mod.parse_tag(args.version)
    except ValueError as exc:
        fail(str(exc))
    assert version is not None

    if version.patch == 0:
        print(f"{version.tag} is a base release; no patches are needed")
        return 0

    current_refs = collect_refs_from_dir()
    try:
        cumulative_count, adjacent_count, prev_patch = describe(version, current_refs)
    except RuntimeError as exc:
        fail(str(exc))

    print(
        f"{version.tag}: {cumulative_count} new asset(s) since {version.base_tag}, "
        f"{adjacent_count} since patch {prev_patch:03d}"
    )
    if args.check:
        return 0

    args.dist.mkdir(parents=True, exist_ok=True)
    try:
        entries = build_patches(version, current_refs, assets.ASSETS_DIR, args.dist)
    except RuntimeError as exc:
        fail(str(exc))

    for entry in entries:
        print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
