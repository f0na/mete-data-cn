#!/usr/bin/env python3
"""Validate servants/*.json, merge them, and build the release packages.

Two archives are produced:

    mete-data-cn.zip          servant.json + manifest.json
    mete-data-cn-servant.zip  Servant/... + SkillIcons/...

Images live outside the repository (`assets/` is gitignored).  They are
downloaded by scripts/assets.py using asset_sources.json and packed into the
resource archive; JSON references them by their path under `assets/`.
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

DATA_ZIP_NAME = "mete-data-cn.zip"
ASSET_ZIP_NAME = "mete-data-cn-servant.zip"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)
import version as version_mod  # noqa: E402  (local helper module)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def collect_image_paths(data: object, path: Path) -> list[str]:
    """Validate that every asset reference is a migrated, local asset path."""
    found: list[str] = []
    for raw in assets.iter_strings(data):
        rel = assets.to_path(raw)
        if rel is None:
            if assets.looks_like_asset_value(raw):
                fail(f"{path.name}: unrecognized asset reference: {raw!r}")
            continue
        if rel != raw:
            fail(
                f"{path.name}: asset link not migrated: {raw!r} -> {rel!r} "
                "(run scripts/migrate_assets.py)"
            )
        found.append(rel)
    return found


def load_servant(path: Path) -> tuple[dict, list[str]]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
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
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_to_zip(
    zf: zipfile.ZipFile,
    source: Path,
    arcname: str,
    compress_type: int = zipfile.ZIP_DEFLATED,
) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compress_type
    info.create_system = 3  # fixed so local Windows builds match Linux CI
    info.external_attr = 0o644 << 16
    zf.writestr(info, source.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="dev", help="release tag written to manifest.json")
    parser.add_argument("--check", action="store_true", help="validate only; do not write dist/")
    parser.add_argument("--check-images", action="store_true", help="also verify assets/ is complete")
    parser.add_argument("--check-sources", action="store_true", help="verify asset_sources.json covers every reference")
    parser.add_argument("--no-images", action="store_true", help="build without the resource archive")
    parser.add_argument("--strict-version", action="store_true", help="fail unless --version is a valid release tag")
    parser.add_argument("--generated-at", help="override manifest generated_at (YYYY-MM-DDTHH:MM:SSZ)")
    args = parser.parse_args()

    parsed_version = version_mod.parse_tag(args.version, strict=False)
    if parsed_version is None and args.strict_version:
        fail(f"invalid release tag: {args.version!r} (expected data-YYYY.MM.DD[.NNN])")

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

    sources = None
    if args.check_sources or not args.check:
        sources = assets.AssetSources.load()
        missing_sources = sorted(rel for rel in image_paths if not sources.get(rel))
        if missing_sources:
            for rel in missing_sources[:20]:
                print(f"  no source URL: {rel}", file=sys.stderr)
            fail(
                f"{len(missing_sources)} asset(s) missing from "
                f"{sources.path.name}; run scripts/fetch.py or add the mapping"
            )
        print(f"Source map covers all {len(image_paths)} referenced asset(s).")

    want_images = not args.no_images
    verify_images = args.check_images if args.check else want_images
    if verify_images:
        missing = [rel for rel in sorted(image_paths) if not (assets.ASSETS_DIR / rel).is_file()]
        if missing:
            for rel in missing[:20]:
                print(f"  missing: {rel}", file=sys.stderr)
            fail(f"image(s) missing from {assets.ASSETS_DIR} (run scripts/assets.py)")

    if args.check:
        print("Check mode: no files written.")
        return 0

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir(parents=True)

    servant_path = DIST_DIR / "servant.json"
    manifest_path = DIST_DIR / "manifest.json"
    data_zip_path = DIST_DIR / DATA_ZIP_NAME
    asset_zip_path = DIST_DIR / ASSET_ZIP_NAME

    write_json(servant_path, servants)
    payload = servant_path.read_bytes()

    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: dict = {"version": args.version, "generated_at": generated_at}
    if parsed_version is not None:
        manifest.update(parsed_version.as_manifest())
    manifest["assets"] = {"root": "."}

    if want_images:
        with zipfile.ZipFile(asset_zip_path, "w") as zf:
            for rel in sorted(image_paths):
                # PNGs are already compressed; storing them keeps the build fast.
                add_to_zip(zf, assets.ASSETS_DIR / rel, rel, zipfile.ZIP_STORED)
        manifest["assets"].update(
            {
                "archive": ASSET_ZIP_NAME,
                "bytes": asset_zip_path.stat().st_size,
                "sha256": sha256_file(asset_zip_path),
            }
        )
        print(f"Built {asset_zip_path}")

    manifest["files"] = [
        {
            "name": "servant.json",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    ]
    write_json(manifest_path, manifest)

    with zipfile.ZipFile(data_zip_path, "w") as zf:
        add_to_zip(zf, servant_path, "servant.json")
        add_to_zip(zf, manifest_path, "manifest.json")

    print(f"Built {data_zip_path}")
    print(f"servant.json sha256: {manifest['files'][0]['sha256']}")
    if want_images:
        print(f"{ASSET_ZIP_NAME} sha256: {manifest['assets']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
