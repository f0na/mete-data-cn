#!/usr/bin/env python3
"""One-off migration from images/CN/... to assets/{Servant,SkillIcons}/....

The migration:
  * moves every file under images/ to the new assets/ layout (same volume
    rename, no copies);
  * writes asset_sources.json, the canonical local-path -> source-URL map;
  * rewrites every path string in servants/*.json.

It is idempotent: running --apply twice is a no-op.  Without --apply it only
prints what would change.

Usage:
    python scripts/migrate_assets.py            # dry run
    python scripts/migrate_assets.py --apply
    python scripts/migrate_assets.py --verify
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVANTS_DIR = ROOT / "servants"
OLD_ROOT = ROOT / "images"
NEW_ROOT = ROOT / "assets"
SOURCES_PATH = ROOT / "asset_sources.json"

ATLAS_BASE = "https://static.atlasacademy.io"
MOONCELL_BASE = "https://media.fgo.wiki"
LEGACY_ROOTS = ("CN/", "fgo.wiki/")

# Longest prefixes first so CN/Servants/... is handled before any shorter rule.
LEGACY_DIRS = (
    ("CN/Servants/Commands/", "Servant/Commands/"),
    ("CN/Servants/Status/", "Servant/Status/"),
    ("CN/CharaGraph/", "Servant/CharaGraph/"),
    ("CN/NarrowFigure/", "Servant/NarrowFigure/"),
    ("CN/Faces/", "Servant/Faces/"),
    ("CN/SkillIcons/", "SkillIcons/"),
)
LEGACY_FILES = {
    "fgo.wiki/3/31/己阵防御.png": "SkillIcons/己阵防御.png",
    "fgo.wiki/d/d9/宝具威力提升.png": "SkillIcons/宝具威力提升.png",
}
REVERSE_FILES = {new: old for old, new in LEGACY_FILES.items()}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def rel_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def old_to_new(old_rel: str) -> str | None:
    if old_rel in LEGACY_FILES:
        return LEGACY_FILES[old_rel]
    for old_prefix, new_prefix in LEGACY_DIRS:
        if old_rel.startswith(old_prefix):
            return new_prefix + old_rel[len(old_prefix) :]
    return None


def new_to_old(new_rel: str) -> str | None:
    if new_rel in REVERSE_FILES:
        return REVERSE_FILES[new_rel]
    for old_prefix, new_prefix in LEGACY_DIRS:
        if new_rel.startswith(new_prefix):
            return old_prefix + new_rel[len(new_prefix) :]
    return None


def legacy_source_url(old_rel: str) -> str:
    """The old source_url() logic, kept only for this one-off migration."""
    if old_rel.startswith("fgo.wiki/"):
        path = old_rel[len("fgo.wiki/") :]
        return MOONCELL_BASE + "/" + urllib.parse.quote(path, safe="/@")
    return ATLAS_BASE + "/" + urllib.parse.quote(old_rel, safe="/@")


def looks_legacy(value: str) -> bool:
    return value.startswith(LEGACY_ROOTS)


def iter_strings(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, str):
        yield value


def walk_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(rel_posix(path, root) for path in root.rglob("*") if path.is_file())


def build_plan() -> tuple[list[tuple[Path, Path, str]], dict[str, str], dict[str, str]]:
    """Return (moves, sources, problems)."""
    moves: list[tuple[Path, Path, str]] = []
    sources: dict[str, str] = {}
    problems: dict[str, str] = {}

    def add_source(new_rel: str, old_rel: str) -> None:
        if new_rel in sources:
            problems[new_rel] = f"duplicate target: {sources[new_rel]} and {old_rel}"
            return
        sources[new_rel] = legacy_source_url(old_rel)

    for old_rel in walk_files(OLD_ROOT):
        new_rel = old_to_new(old_rel)
        if new_rel is None:
            problems[old_rel] = "unmapped legacy path"
            continue
        moves.append((OLD_ROOT / old_rel, NEW_ROOT / new_rel, old_rel))
        add_source(new_rel, old_rel)

    # Files already in the new layout (resume after a partial migration).
    for new_rel in walk_files(NEW_ROOT):
        if new_rel in sources:
            continue
        old_rel = new_to_old(new_rel)
        if old_rel is None:
            problems[new_rel] = "existing asset outside the known layout"
            continue
        add_source(new_rel, old_rel)

    return moves, sources, problems


def apply_moves(moves: list[tuple[Path, Path, str]], force: bool) -> int:
    moved = 0
    total = len(moves)
    for index, (source, target, old_rel) in enumerate(moves, 1):
        if target.exists():
            if target.stat().st_size == source.stat().st_size:
                if not force:
                    fail(
                        f"target already exists with the same size: {target} "
                        "(rerun with --force to overwrite)"
                    )
            elif not force:
                fail(f"target already exists: {target} (rerun with --force to overwrite)")
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.rename(target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.move(str(source), str(target))
        moved += 1
        if index % 1000 == 0 or index == total:
            print(f"  moved {index}/{total}")
    return moved


def remove_empty_dirs(root: Path) -> None:
    if not root.is_dir():
        return
    for current, _dirs, _files in os.walk(root, topdown=False):
        try:
            Path(current).rmdir()
        except OSError:
            pass


def load_sources() -> dict[str, str]:
    if not SOURCES_PATH.is_file():
        return {}
    raw = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        fail(f"{SOURCES_PATH}: unsupported schema")
    entries = raw.get("sources")
    if not isinstance(entries, dict):
        fail(f"{SOURCES_PATH}: missing 'sources' object")
    return {str(key): str(value) for key, value in entries.items()}


def write_sources(sources: dict[str, str], force: bool) -> None:
    existing = load_sources()
    merged = dict(existing)
    for local, url in sources.items():
        old = merged.get(local)
        if old is not None and old != url:
            if not force:
                fail(
                    f"source URL mismatch for {local}: existing {old!r}, "
                    f"migration produced {url!r} (rerun with --force to trust the migration)"
                )
            print(f"warning: replacing source URL for {local}")
            merged[local] = url
        else:
            merged.setdefault(local, url)

    payload = {"schema": 1, "sources": dict(sorted(merged.items()))}
    tmp = SOURCES_PATH.with_name(SOURCES_PATH.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=0, sort_keys=True)
        handle.write("\n")
    tmp.replace(SOURCES_PATH)
    print(f"wrote {SOURCES_PATH.name} ({len(merged)} entries)")


def rewrite_servants() -> int:
    changed_files = 0
    changed_strings = 0
    for path in sorted(SERVANTS_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)

        local_changes = 0

        def rewrite(value: object) -> object:
            nonlocal local_changes
            if isinstance(value, dict):
                return {key: rewrite(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rewrite(item) for item in value]
            if isinstance(value, str) and looks_legacy(value):
                new_value = old_to_new(value)
                if new_value is None:
                    fail(f"{path.name}: no migration rule for {value!r}")
                local_changes += 1
                return new_value
            return value

        updated = rewrite(data)
        if local_changes:
            tmp = path.with_name(path.name + ".tmp")
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(updated, handle, indent=4, ensure_ascii=False)
                handle.write("\n")
            tmp.replace(path)
            changed_files += 1
            changed_strings += local_changes
    print(f"rewrote {changed_strings} path(s) in {changed_files} servant file(s)")
    return changed_files


def verify() -> None:
    problems: list[str] = []

    if OLD_ROOT.exists():
        remaining = walk_files(OLD_ROOT)
        if remaining:
            problems.append(f"{OLD_ROOT} still contains {len(remaining)} file(s)")

    files = set(walk_files(NEW_ROOT))
    if not SOURCES_PATH.is_file():
        problems.append(f"{SOURCES_PATH.name} is missing")
        sources: dict[str, str] = {}
    else:
        sources = load_sources()
    if set(sources) != files:
        only_files = sorted(files - set(sources))[:5]
        only_sources = sorted(set(sources) - files)[:5]
        problems.append(
            f"asset/files mismatch: {len(files)} files, {len(sources)} sources; "
            f"files without source={only_files}, sources without file={only_sources}"
        )

    refs: set[str] = set()
    for path in sorted(SERVANTS_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        for value in iter_strings(data):
            if looks_legacy(value):
                problems.append(f"{path.name}: legacy path remains: {value!r}")
            elif value.startswith(("http://", "https://")):
                problems.append(f"{path.name}: URL remains: {value!r}")
            elif value.startswith(("Servant/", "SkillIcons/")):
                refs.add(value)

    missing_files = sorted(refs - files)[:10]
    missing_sources = sorted(refs - set(sources))[:10]
    if missing_files:
        problems.append(f"referenced assets missing from disk: {missing_files}")
    if missing_sources:
        problems.append(f"referenced assets missing from sources: {missing_sources}")

    if problems:
        for problem in problems[:20]:
            print(f"  {problem}", file=sys.stderr)
        fail(f"migration verification failed ({len(problems)} problem(s))")

    print(
        f"verified: {len(files)} files, {len(sources)} sources, "
        f"{len(refs)} referenced paths"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    parser.add_argument("--verify", action="store_true", help="verify an applied migration")
    parser.add_argument("--force", action="store_true", help="overwrite conflicting targets")
    args = parser.parse_args()

    if args.verify:
        verify()
        return 0

    moves, sources, problems = build_plan()
    if problems:
        for key, problem in list(problems.items())[:20]:
            print(f"  {key}: {problem}", file=sys.stderr)
        fail(f"cannot build migration plan ({len(problems)} problem(s))")

    print(f"files to move: {len(moves)}")
    print(f"source entries: {len(sources)}")
    for source, target, _old in moves[:5]:
        print(f"  {source} -> {target}")
    if len(moves) > 5:
        print(f"  ... and {len(moves) - 5} more")

    if not args.apply:
        print("dry run: rerun with --apply to migrate")
        return 0

    apply_moves(moves, args.force)
    remove_empty_dirs(OLD_ROOT)
    write_sources(sources, args.force)
    rewrite_servants()
    verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
