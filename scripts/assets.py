#!/usr/bin/env python3
"""Mirror servant image assets into a local cache and store asset paths in JSON.

Images are NOT committed to the repository.  They are downloaded into
`images/` (gitignored) and packed into the release zip by scripts/build.py.
JSON stores the path relative to the manifest's `assets.root`:

    "assets": {"chara_graph": "CN/CharaGraph/100100/100100a@1.png"}

Consumers resolve it as `<zip root>/images/<path>`.  Source URLs are Atlas
Academy's static CDN and Mooncell media; legacy URLs (including old jsDelivr
links) are converted to paths, so the script is idempotent.

Usage:
    python scripts/assets.py                  # download missing files + store paths
    python scripts/assets.py --jobs 24        # more parallel downloads
    python scripts/assets.py --check          # verify assets exist, do not download
    python scripts/assets.py --no-download    # only convert URLs to paths
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
IMAGES_DIR = ROOT / "images"

ATLAS_BASE = "https://static.atlasacademy.io"
MOONCELL_BASE = "https://media.fgo.wiki"
LOCAL_ROOTS = ("CN/", "fgo.wiki/")

USER_AGENT = "mete-data-cn/1.0"
RETRIES = 4


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


def to_path(value: object) -> str | None:
    """Convert a known image URL (or existing asset path) to its images/ path."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme:
        host = parsed.netloc
        path = urllib.parse.unquote(parsed.path)
        if host == "static.atlasacademy.io":
            return _sanitize(path)
        if host == "media.fgo.wiki":
            return _sanitize("fgo.wiki/" + path)
        if host.endswith("jsdelivr.net") and "/images/" in path:
            return _sanitize(path.split("/images/", 1)[1])
        return None
    if value.startswith(LOCAL_ROOTS):
        return _sanitize(value)
    return None


def source_url(rel: str) -> str:
    if rel.startswith("fgo.wiki/"):
        return MOONCELL_BASE + "/" + urllib.parse.quote(rel[len("fgo.wiki/") :], safe="/@")
    return ATLAS_BASE + "/" + urllib.parse.quote(rel, safe="/@")


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
    """Collect image paths referenced by a servant object."""
    for text in iter_strings(value):
        path = to_path(text)
        if path is not None and path not in seen:
            seen.add(path)
            found.append(path)


def rewrite(value: object) -> object:
    """Replace image URLs with their images/ paths, leaving everything else."""
    if isinstance(value, dict):
        return {key: rewrite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite(item) for item in value]
    if isinstance(value, str):
        path = to_path(value)
        if path is not None:
            return path
    return value


def download(rel: str) -> bool:
    """Download one image unless it already exists.  Returns True if fetched."""
    dest = IMAGES_DIR / rel
    if dest.is_file() and dest.stat().st_size > 0:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = source_url(rel)
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


def download_many(paths: list[str], jobs: int) -> None:
    """Download the given images, skipping ones already mirrored."""
    print(f"downloading {len(paths)} image(s) with {jobs} worker(s) ...")
    done = 0
    failed = 0
    processed = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(download, rel): rel for rel in paths}
        for future in as_completed(futures):
            rel = futures[future]
            processed += 1
            try:
                fetched = future.result()
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                print(f"  {rel}: {exc}")
            else:
                if fetched:
                    done += 1
            if processed % 100 == 0 or processed == len(paths):
                elapsed = time.monotonic() - started
                print(f"  {processed}/{len(paths)} ({done} new, {failed} failed, {elapsed:.0f}s)")
    if failed:
        fail(f"{failed} image(s) could not be downloaded")


def localize(value: object, download_files: bool = True, jobs: int = 16) -> object:
    """Store asset paths in a servant object and download the referenced images."""
    refs: list[str] = []
    collect(value, refs, set())
    if download_files:
        download_many(refs, jobs)
    return rewrite(value)


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=16, help="parallel downloads")
    parser.add_argument("--check", action="store_true", help="verify only; do not download or write")
    parser.add_argument("--no-download", action="store_true", help="convert links without downloading")
    args = parser.parse_args()

    files = sorted(SERVANTS_DIR.glob("*.json"))
    if not files:
        fail(f"no servant files found in {SERVANTS_DIR}")

    servants = []
    refs: list[str] = []
    seen: set[str] = set()
    for path in files:
        data = read_json(path)
        servants.append((path, data))
        collect(data, refs, seen)

    if args.check:
        missing = [rel for rel in refs if not (IMAGES_DIR / rel).is_file()]
        if missing:
            for rel in missing:
                print(f"  missing: {rel}")
            fail(f"image(s) missing from {IMAGES_DIR}")
        print("ok: all referenced images present")
        return 0

    if not args.no_download:
        download_many(refs, args.jobs)

    for path, data in servants:
        updated = rewrite(data)
        if updated != data:
            write_json(path, updated)
    print("asset paths stored in JSON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
