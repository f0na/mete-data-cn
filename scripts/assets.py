#!/usr/bin/env python3
"""Mirror game image assets using an explicit local-path -> source-URL map.

Images are NOT committed to the repository.  They are downloaded into
`assets/` (gitignored) and packed into one resource archive per dataset by
scripts/build.py.  JSON stores paths relative to `assets/`:

    "assets": {"chara_graph": "Servant/CharaGraph/100100/100100a@1.png"}

Asset roots by dataset: `Servant/` + `SkillIcons/` (servants), `Craft/`,
`Mystic/`, `Cmdcodes/`.

`asset_sources.json` is the authoritative list of where each local asset came
from.  Downloads only use that map; nothing is inferred from the local path.
If a referenced path has no entry, the script fails instead of guessing.

Usage:
    python scripts/assets.py                  # download missing files
    python scripts/assets.py --jobs 24        # more parallel downloads
    python scripts/assets.py --check          # verify files and mappings
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVANTS_DIR = ROOT / "servants"
DATA_DIRS = {
    "servants": SERVANTS_DIR,
    "crafts": ROOT / "crafts",
    "mystic": ROOT / "mystic",
    "cmdcodes": ROOT / "cmdcodes",
}
ASSETS_DIR = ROOT / "assets"
SOURCES_PATH = ROOT / "asset_sources.json"

ATLAS_BASE = "https://static.atlasacademy.io"
MOONCELL_BASE = "https://media.fgo.wiki"
LOCAL_ROOTS = ("Servant/", "SkillIcons/", "Craft/", "Mystic/", "Cmdcodes/")
LEGACY_ROOTS = ("CN/", "fgo.wiki/")
ASSET_HOSTS = ("static.atlasacademy.io", "media.fgo.wiki")

USER_AGENT = "mete-data-cn/1.0"
RETRIES = 4

# One-off migration rules; kept so legacy JSON paths fail loudly instead of
# being silently skipped while the repository transitions to the new layout.
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


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _sanitize(rel: str) -> str | None:
    rel = rel.replace("\\", "/").strip("/")
    if not rel:
        return None
    parts = [part for part in rel.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def legacy_to_local(rel: str) -> str | None:
    """Map an old images/ path to its new assets/ path, if known."""
    rel = rel.replace("\\", "/").strip("/")
    if rel in LEGACY_FILES:
        return LEGACY_FILES[rel]
    for old_prefix, new_prefix in LEGACY_DIRS:
        if rel.startswith(old_prefix):
            return _sanitize(new_prefix + rel[len(old_prefix) :])
    return None


def _is_asset_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.netloc
    return host in ASSET_HOSTS or host.endswith("jsdelivr.net")


def url_to_path(value: str) -> str | None:
    """Convert a known asset URL to its assets/ path."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc
    path = urllib.parse.unquote(parsed.path)
    if host == "static.atlasacademy.io":
        return legacy_to_local(_sanitize(path) or "")
    if host == "media.fgo.wiki":
        return legacy_to_local(_sanitize("fgo.wiki/" + path) or "")
    if host.endswith("jsdelivr.net") and "/images/" in path:
        return legacy_to_local(_sanitize(path.split("/images/", 1)[1]) or "")
    return None


def to_path(value: object) -> str | None:
    """Convert a known asset URL or (old/new) local path to an assets/ path."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme:
        return url_to_path(value)
    if value.startswith(LOCAL_ROOTS):
        return _sanitize(value)
    if value.startswith(LEGACY_ROOTS):
        return legacy_to_local(value)
    return None


def looks_like_asset_value(value: object) -> bool:
    """Whether a string is meant to be an asset reference (not arbitrary text)."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value:
        return False
    if value.startswith(LOCAL_ROOTS) or value.startswith(LEGACY_ROOTS):
        return True
    return _is_asset_url(value)


def iter_strings(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
    elif isinstance(value, str):
        yield value


def collect(value: object, found: list[str], seen: set[str]) -> None:
    """Collect asset paths referenced by a servant object."""
    for text in iter_strings(value):
        path = to_path(text)
        if path is not None and path not in seen:
            seen.add(path)
            found.append(path)


def rewrite(value: object, sources: "AssetSources | None" = None) -> object:
    """Replace asset URLs / legacy paths with their new local paths."""
    if isinstance(value, dict):
        return {key: rewrite(item, sources) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite(item, sources) for item in value]
    if isinstance(value, str):
        parsed = urllib.parse.urlsplit(value.strip())
        if parsed.scheme in ("http", "https"):
            path = url_to_path(value)
            if path is None:
                if _is_asset_url(value):
                    raise ValueError(f"unmapped asset URL: {value}")
                return value
            if sources is not None:
                sources.record(path, value)
            return path
        if value.startswith(LEGACY_ROOTS):
            path = legacy_to_local(value)
            if path is None:
                raise ValueError(f"unmapped legacy asset path: {value}")
            return path
    return value


class AssetSources:
    """The committed local-path -> source-URL map."""

    SCHEMA = 1

    def __init__(self, path: Path = SOURCES_PATH, entries: dict[str, str] | None = None):
        self.path = path
        self.entries: dict[str, str] = dict(entries or {})

    @classmethod
    def load(cls, path: Path = SOURCES_PATH, *, missing_ok: bool = False) -> "AssetSources":
        if not path.is_file():
            if missing_ok:
                return cls(path)
            fail(
                f"missing {path.name}; it is the authoritative asset source map "
                "(run scripts/migrate_assets.py or restore it from git)"
            )
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{path.name}: invalid JSON ({exc})")
        if not isinstance(raw, dict) or raw.get("schema") != cls.SCHEMA:
            fail(f"{path.name}: unsupported schema (expected {cls.SCHEMA})")
        entries = raw.get("sources")
        if not isinstance(entries, dict):
            fail(f"{path.name}: missing 'sources' object")

        clean: dict[str, str] = {}
        for key, value in entries.items():
            if not isinstance(key, str) or not isinstance(value, str):
                fail(f"{path.name}: sources entries must be string -> string")
            local = _sanitize(key)
            if local is None:
                fail(f"{path.name}: invalid asset path {key!r}")
            if local in clean:
                fail(f"{path.name}: duplicate asset path {local!r}")
            clean[local] = value
        return cls(path, clean)

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, local: str) -> str | None:
        return self.entries.get(local)

    def record(self, local: str, url: str) -> bool:
        local = _sanitize(local) or ""
        if not local:
            return False
        current = self.entries.get(local)
        if current is None:
            self.entries[local] = url
            return True
        if current != url:
            print(
                f"warning: source URL for {local} is {current!r}; "
                f"ignoring {url!r}",
                file=sys.stderr,
            )
        return False

    def save(self) -> None:
        payload = {"schema": self.SCHEMA, "sources": dict(sorted(self.entries.items()))}
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=0, sort_keys=True)
            handle.write("\n")
        tmp.replace(self.path)


def download(rel: str, url: str) -> bool:
    """Download one asset unless it already exists.  Returns True if fetched."""
    dest = ASSETS_DIR / rel
    if dest.is_file() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read()
            if not data:
                raise RuntimeError("empty response")
            part.write_bytes(data)
            part.replace(dest)
            return True
        except Exception as exc:  # noqa: BLE001 - network errors are retried
            last = exc
            part.unlink(missing_ok=True)
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f"failed to download {url}: {last}")


def download_many(paths: list[str], jobs: int, sources: AssetSources) -> None:
    """Download the given assets using the source map; never infer URLs."""
    missing = [rel for rel in paths if not sources.get(rel)]
    if missing:
        for rel in missing[:20]:
            print(f"  no source URL: {rel}", file=sys.stderr)
        fail(
            f"{len(missing)} asset(s) have no entry in {sources.path.name}; "
            "run scripts/fetch.py or add the mapping manually"
        )

    print(f"downloading {len(paths)} image(s) with {jobs} worker(s) ...")
    done = 0
    failed = 0
    processed = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(download, rel, sources.get(rel)): rel for rel in paths}
        for future in as_completed(futures):
            rel = futures[future]
            processed += 1
            try:
                fetched = future.result()
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"  {rel}: {exc}", file=sys.stderr)
            else:
                if fetched:
                    done += 1
            if processed % 100 == 0 or processed == len(paths):
                elapsed = time.monotonic() - started
                print(f"  {processed}/{len(paths)} ({done} new, {failed} failed, {elapsed:.0f}s)")
    if failed:
        fail(f"{failed} image(s) could not be downloaded")


def localize(
    value: object,
    sources: AssetSources,
    download_files: bool = True,
    jobs: int = 16,
) -> object:
    """Store asset paths in a servant object and download the referenced files."""
    localized = rewrite(value, sources)
    refs: list[str] = []
    collect(localized, refs, set())
    if download_files:
        download_many(refs, jobs, sources)
    return localized


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=16, help="parallel downloads")
    parser.add_argument("--check", action="store_true", help="verify only; do not download")
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH, help="source map path")
    parser.add_argument(
        "--dataset",
        choices=sorted(DATA_DIRS),
        action="append",
        help="only process this dataset (repeatable; default: all)",
    )
    args = parser.parse_args()

    datasets = args.dataset or sorted(DATA_DIRS)
    files: list[Path] = []
    for name in datasets:
        directory = DATA_DIRS[name]
        if not directory.is_dir():
            continue
        files.extend(sorted(directory.glob("*.json")))
    if not files:
        fail(f"no data files found in {', '.join(str(DATA_DIRS[name]) for name in datasets)}")

    sources = AssetSources.load(args.sources)
    refs: list[str] = []
    seen: set[str] = set()
    for path in files:
        data = read_json(path)
        collect(data, refs, seen)

    missing_sources = [rel for rel in refs if not sources.get(rel)]
    missing_files = [rel for rel in refs if not (ASSETS_DIR / rel).is_file()]

    if missing_sources:
        for rel in missing_sources[:20]:
            print(f"  no source URL: {rel}", file=sys.stderr)
        fail(f"{len(missing_sources)} referenced asset(s) missing from {args.sources.name}")

    if args.check:
        if missing_files:
            for rel in missing_files[:20]:
                print(f"  missing: {rel}", file=sys.stderr)
            fail(f"{len(missing_files)} image(s) missing from {ASSETS_DIR}")
        print(f"ok: {len(refs)} referenced image(s) present and mapped")
        return 0

    if missing_files:
        download_many(missing_files, args.jobs, sources)
    else:
        print(f"ok: all {len(refs)} referenced image(s) already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
