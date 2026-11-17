#!/usr/bin/env python3
"""Validate servants/*.json, merge them, and build the release package."""

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


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_servant(path: Path) -> dict:
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

    return data


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def add_to_zip(zf: zipfile.ZipFile, source: Path, arcname: str) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, source.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="dev", help="version written to manifest.json")
    parser.add_argument("--check", action="store_true", help="validate only; do not write dist/")
    args = parser.parse_args()

    if not SERVANTS_DIR.is_dir():
        fail(f"missing servants directory: {SERVANTS_DIR}")

    files = sorted(SERVANTS_DIR.glob("*.json"))
    if not files:
        fail(f"no servant files found in {SERVANTS_DIR}")

    servants: list[dict] = []
    seen: dict[int, str] = {}
    for path in files:
        data = load_servant(path)
        sid = data["id"]
        if sid in seen:
            fail(f"{path.name}: duplicate id {sid} (also in {seen[sid]})")
        seen[sid] = path.name
        servants.append(data)

    servants.sort(key=lambda item: item["id"])
    ids = [item["id"] for item in servants]
    print(f"Validated {len(servants)} servant file(s): {', '.join(map(str, ids))}")

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
    manifest = {
        "version": args.version,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "servant_count": len(servants),
        "servant_ids": ids,
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

    print(f"Built {zip_path} ({zip_path.stat().st_size} bytes, {len(servants)} servants)")
    print(f"servant.json sha256: {manifest['files'][0]['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
