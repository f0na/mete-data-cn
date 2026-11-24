#!/usr/bin/env python3
"""Validate servants/*.json, merge them, and build the release package.

Images live outside the repository (`images/` is gitignored).  They are
downloaded by scripts/assets.py and packed into mete-data-cn.zip next to
servant.json; JSON references them by their path under `images/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVANTS_DIR = ROOT / "servants"
DIST_DIR = ROOT / "dist"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def collect_image_paths(data: object, path: Path) -> list[str]:
    """Validate that every image reference is a local asset path."""
    found: list[str] = []
    for raw in assets.iter_strings(data):
        rel = assets.to_path(raw)
        if rel is None:
            continue
        if rel != raw:
            fail(f"{path.name}: image link not localized: {raw} (run scripts/assets.py)")
        found.append(rel)
    return found


def load_servant(path: Path) -> tuple[dict, list[str]]:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        fail(f"{path.name}: invalid JSON ({exc})")

    if not isinstance(data, dict):
        fail(f"{path.name}: expected a single JSON object")

    sid = data.get("id")
    if not isinstance(sid, int) or isinstance(sid, bool) or sid <= 0:
        fail(f"{path.name}: invalid 'id' value {sid!r}")
    if path.stem != str(sid):
        fail(f"{path.name}: file name must match id (expected {sid}.json)")

    return data, collect_image_paths(data, path)


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def add_to_zip(
    zf: zipfile.ZipFile,
    source: Path,
    arcname: str,
    compress_type: int = zipfile.ZIP_DEFLATED,
) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compress_type
    info.external_attr = 0o644 << 16
    zf.writestr(info, source.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="dev", help="version written to manifest.json")
    parser.add_argument("--check", action="store_true", help="validate only; do not write dist/")
    parser.add_argument("--check-images", action="store_true", help="also verify images/ is complete")
    parser.add_argument("--no-images", action="store_true", help="build without packing images")
    args = parser.parse_args()

    if not SERVANTS_DIR.is_dir():
        fail(f"missing servants directory: {SERVANTS_DIR}")

    files = sorted(SERVANTS_DIR.glob("*.json"))
    if not files:
        fail(f"no servant files found in {SERVANTS_DIR}")

    servants: list[dict] = []
    seen: dict[int, str] = {}
    image_paths: set[str] = set()
    for path in files:
        data, refs = load_servant(path)
        sid = data["id"]
        if sid in seen:
            fail(f"{path.name}: duplicate id {sid} (also in {seen[sid]})")
        seen[sid] = path.name
        servants.append(data)
        image_paths.update(refs)

    servants.sort(key=lambda item: item["id"])
    print("Validated servant files.")

    want_images = not args.no_images
    verify_images = args.check_images if args.check else want_images
    if verify_images:
        missing = [rel for rel in sorted(image_paths) if not (assets.IMAGES_DIR / rel).is_file()]
        if missing:
            for rel in missing[:20]:
                print(f"  missing: {rel}")
            fail(f"image(s) missing from {assets.IMAGES_DIR} (run scripts/assets.py)")

    if args.check:
        print("Check mode: no files written.")
        return 0

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    servant_path = DIST_DIR / "servant.json"
    manifest_path = DIST_DIR / "manifest.json"
    zip_path = DIST_DIR / "mete-data-cn.zip"

    write_json(servant_path, servants)

    payload = servant_path.read_bytes()
    packed_images = sorted(image_paths) if want_images else []
    manifest = {
        "version": args.version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "assets": {
            "root": "images",
        },
        "files": [
            {
                "name": "servant.json",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }
    write_json(manifest_path, manifest)

    with zipfile.ZipFile(zip_path, "w") as zf:
        add_to_zip(zf, servant_path, "servant.json")
        add_to_zip(zf, manifest_path, "manifest.json")
        for rel in packed_images:
            # PNGs are already compressed; storing them keeps the build fast.
            add_to_zip(zf, assets.IMAGES_DIR / rel, f"images/{rel}", zipfile.ZIP_STORED)

    print(f"Built {zip_path}")
    print(f"servant.json sha256: {manifest['files'][0]['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
