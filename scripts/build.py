#!/usr/bin/env python3
"""Validate the per-id datasets and build the release packages.

Layout:

    mete-data-cn.zip           all merged JSON files + manifest.json
    mete-data-cn-servant.zip   Servant/... + SkillIcons/...
    mete-data-cn-craft.zip     Craft/...
    mete-data-cn-mystic.zip    Mystic/...
    mete-data-cn-cmdcode.zip   Cmdcodes/...

JSON is always downloaded as one full data package; images are split by
dataset so a client can fetch only the resource packages it needs.  Images
live outside the repository (`assets/` is gitignored), are downloaded by
scripts/assets.py from asset_sources.json, and are packed into the resource
archives; JSON references them by their path under `assets/`.
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
DIST_DIR = ROOT / "dist"

DATA_ZIP_NAME = "mete-data-cn.zip"

# key -> directory, merged file name, resource archive, asset roots, patch prefix
DATASETS = {
    "servant": {
        "dir": ROOT / "servants",
        "file": "servant.json",
        "archive": "mete-data-cn-servant.zip",
        "roots": ("Servant/", "SkillIcons/"),
        "prefix": "",
    },
    "craft": {
        "dir": ROOT / "crafts",
        "file": "craft.json",
        "archive": "mete-data-cn-craft.zip",
        "roots": ("Craft/",),
        "prefix": "craft",
    },
    "mystic": {
        "dir": ROOT / "mystic",
        "file": "mystic.json",
        "archive": "mete-data-cn-mystic.zip",
        "roots": ("Mystic/",),
        "prefix": "mystic",
    },
    "cmdcode": {
        "dir": ROOT / "cmdcodes",
        "file": "cmdcode.json",
        "archive": "mete-data-cn-cmdcode.zip",
        "roots": ("Cmdcodes/",),
        "prefix": "cmdcode",
    },
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive  # noqa: E402  (local helper module)
import assets  # noqa: E402  (local helper module)
import patches as patches_mod  # noqa: E402  (local helper module)
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
                "(run the matching fetch script)"
            )
        found.append(rel)
    return found


def load_entries(key: str, spec: dict) -> tuple[list[dict], list[str]]:
    directory = spec["dir"]
    if not directory.is_dir():
        fail(f"missing {key} directory: {directory}")

    files = sorted(directory.glob("*.json"))
    if not files:
        fail(f"no {key} files found in {directory}")

    entries: list[dict] = []
    seen: dict[int, str] = {}
    refs: set[str] = set()
    for path in files:
        try:
            with path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            fail(f"{path.name}: invalid JSON ({exc})")

        if not isinstance(data, dict):
            fail(f"{path.name}: expected a single JSON object")

        entry_id = data.get("id")
        if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
            fail(f"{path.name}: invalid 'id' value {entry_id!r}")
        if path.stem != str(entry_id):
            fail(f"{path.name}: file name must match id (expected {entry_id}.json)")
        if entry_id in seen:
            fail(f"{path.name}: duplicate id {entry_id} (also in {seen[entry_id]})")
        seen[entry_id] = path.name

        image_refs = collect_image_paths(data, path)
        unexpected = [rel for rel in image_refs if not rel.startswith(spec["roots"])]
        if unexpected:
            fail(
                f"{path.name}: asset outside {'/'.join(spec['roots'])}: "
                f"{unexpected[0]!r}"
            )
        refs.update(image_refs)
        entries.append(data)

    entries.sort(key=lambda item: item["id"])
    print(f"Validated {len(entries)} {key} file(s).")
    return entries, sorted(refs)


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, indent=4, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="dev", help="release tag written to manifest.json")
    parser.add_argument("--check", action="store_true", help="validate only; do not write dist/")
    parser.add_argument("--check-images", action="store_true", help="also verify assets/ is complete")
    parser.add_argument("--check-sources", action="store_true", help="verify asset_sources.json covers every reference")
    parser.add_argument("--no-images", action="store_true", help="build without the resource archives")
    parser.add_argument("--no-patches", action="store_true", help="skip incremental patch archives")
    parser.add_argument("--strict-version", action="store_true", help="fail unless --version is a valid release tag")
    parser.add_argument("--generated-at", help="override manifest generated_at (YYYY-MM-DDTHH:MM:SSZ)")
    args = parser.parse_args()

    parsed_version = version_mod.parse_tag(args.version, strict=False)
    if parsed_version is None and args.strict_version:
        fail(f"invalid release tag: {args.version!r} (expected data-YYYY.MM.DD[.NNN])")

    entries_by_dataset: dict[str, list[dict]] = {}
    refs_by_dataset: dict[str, list[str]] = {}
    for key, spec in DATASETS.items():
        entries_by_dataset[key], refs_by_dataset[key] = load_entries(key, spec)

    all_refs = {rel for refs in refs_by_dataset.values() for rel in refs}
    print(f"Validated {len(all_refs)} referenced asset(s).")

    sources = None
    if args.check_sources or not args.check:
        sources = assets.AssetSources.load()
        missing_sources = sorted(rel for rel in all_refs if not sources.get(rel))
        if missing_sources:
            for rel in missing_sources[:20]:
                print(f"  no source URL: {rel}", file=sys.stderr)
            fail(
                f"{len(missing_sources)} asset(s) missing from "
                f"{sources.path.name}; run the matching fetch script or add the mapping"
            )
        print(f"Source map covers all {len(all_refs)} referenced asset(s).")

    want_images = not args.no_images
    verify_images = args.check_images if args.check else want_images
    if verify_images:
        missing = [rel for rel in sorted(all_refs) if not (assets.ASSETS_DIR / rel).is_file()]
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

    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest: dict = {"version": args.version, "generated_at": generated_at}
    if parsed_version is not None:
        manifest.update(parsed_version.as_manifest())

    resources: dict[str, dict] = {}
    files: list[dict] = []

    for key, spec in DATASETS.items():
        data_path = DIST_DIR / spec["file"]
        write_json(data_path, entries_by_dataset[key])
        payload = data_path.read_bytes()
        files.append(
            {
                "name": spec["file"],
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

        resource: dict = {"root": "."}
        if want_images:
            archive_path = DIST_DIR / spec["archive"]
            with zipfile.ZipFile(archive_path, "w") as zf:
                for rel in refs_by_dataset[key]:
                    # PNGs are already compressed; storing them keeps the build fast.
                    archive.add_file(zf, assets.ASSETS_DIR / rel, rel, zipfile.ZIP_STORED)
            resource.update(
                {
                    "archive": spec["archive"],
                    "bytes": archive_path.stat().st_size,
                    "sha256": archive.sha256_file(archive_path),
                }
            )
            print(f"Built {archive_path}")

            if parsed_version is not None and parsed_version.patch > 0 and not args.no_patches:
                try:
                    patches = patches_mod.build_patches(
                        parsed_version,
                        set(refs_by_dataset[key]),
                        assets.ASSETS_DIR,
                        DIST_DIR,
                        directory=spec["dir"],
                        prefix=spec["prefix"],
                    )
                except RuntimeError as exc:
                    fail(str(exc))
                if patches:
                    resource["patches"] = patches

        resources[key] = resource

    manifest["resources"] = resources
    if want_images:
        manifest["assets"] = {
            field: resources["servant"][field]
            for field in ("root", "archive", "bytes", "sha256")
        }
        if resources["servant"].get("patches"):
            manifest["patches"] = resources["servant"]["patches"]
    manifest["files"] = files

    manifest_path = DIST_DIR / "manifest.json"
    write_json(manifest_path, manifest)

    data_zip_path = DIST_DIR / DATA_ZIP_NAME
    with zipfile.ZipFile(data_zip_path, "w") as zf:
        for spec in DATASETS.values():
            archive.add_file(zf, DIST_DIR / spec["file"], spec["file"])
        archive.add_file(zf, manifest_path, "manifest.json")
    print(f"Built {data_zip_path}")

    for entry in files:
        print(f"{entry['name']} sha256: {entry['sha256']}")
    if want_images:
        for key, resource in resources.items():
            print(f"{key} {resource['archive']} sha256: {resource['sha256']}")
            for patch in resource.get("patches") or []:
                print(f"{key} {patch['archive']} sha256: {patch['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
