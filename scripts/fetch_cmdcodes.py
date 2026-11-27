#!/usr/bin/env python3
"""Convert the Atlas Academy CN nice_command_code export into cmdcodes/<id>.json.

Each command code becomes one compact object:

    id, name, rarity,
    assets    (chara_graph / faces, source URLs),
    skills[]  (name / icon / effect),
    comment   (in-game profile text)

Existing files are left untouched unless --overwrite is given, so a run only
adds command codes that are not present.

Examples:
    python scripts/fetch_cmdcodes.py --source nice_command_code.json
    python scripts/fetch_cmdcodes.py --source nice_command_code.json --overwrite
    python scripts/fetch_cmdcodes.py                      # downloads the export first
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CMDCODES_DIR = ROOT / "cmdcodes"
DEFAULT_URL = "https://api.atlasacademy.io/export/CN/nice_command_code.json"

ASSET_KEYS = {
    "chara_graph": "charaGraph",
    "faces": "faces",
}

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)
import dataset_assets  # noqa: E402  (local helper module)


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mete-data-cn/1.0"})
    with urllib.request.urlopen(req) as resp, tmp.open("wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 1048576:.1f}/{total / 1048576:.1f} MiB", end="", flush=True)
    print()
    tmp.replace(target)


def load_export(args: argparse.Namespace) -> list[dict]:
    if args.source:
        path = Path(args.source)
        if not path.is_file():
            fail(f"source not found: {path}")
    else:
        path = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "atlas_cn_nice_command_code.json"
        if not path.is_file():
            download(args.url, path)
        else:
            print(f"using cached export: {path}")

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        fail(f"{path}: expected a non-empty JSON array")
    return data


def localize(url: object, sources: assets.AssetSources) -> str:
    return dataset_assets.localize(url, dataset_assets.CMDCODE_RULES, sources)


def first_asset(extra: dict, asset_key: str) -> str:
    group = extra.get(asset_key) or {}
    urls = [url for values in group.values() for _key, url in sorted(values.items()) if url]
    return urls[0] if urls else ""


def convert_cmdcode(code: dict, sources: assets.AssetSources) -> dict:
    extra = code.get("extraAssets") or {}
    return {
        "id": int(code["id"]),
        "name": str(code.get("name") or ""),
        "rarity": int(code.get("rarity") or 0),
        "assets": {
            field: localize(first_asset(extra, asset_key), sources)
            for field, asset_key in ASSET_KEYS.items()
        },
        "skills": [
            {
                "name": str(skill.get("name") or ""),
                "icon": localize(skill.get("icon"), sources),
                "effect": str(skill.get("detail") or ""),
            }
            for skill in code.get("skills") or []
        ],
        "comment": str(code.get("comment") or ""),
    }


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="local nice_command_code.json (skip downloading)")
    parser.add_argument("--cache", help="where to cache the downloaded export")
    parser.add_argument("--url", default=DEFAULT_URL, help="export URL")
    parser.add_argument("--out-dir", type=Path, default=CMDCODES_DIR)
    parser.add_argument("--ids", nargs="*", type=int, help="only convert these command code ids")
    parser.add_argument("--overwrite", action="store_true", help="replace existing command code files")
    args = parser.parse_args()

    data = load_export(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sources = assets.AssetSources.load()

    wanted = set(args.ids) if args.ids else None
    written = 0
    skipped = 0
    try:
        for code in data:
            code_id = code.get("id")
            if code_id is None or (wanted is not None and code_id not in wanted):
                continue
            path = args.out_dir / f"{code_id}.json"
            if path.exists() and not args.overwrite:
                skipped += 1
                continue
            write_json(path, convert_cmdcode(code, sources))
            written += 1
    finally:
        sources.save()

    print(f"wrote {written} command code file(s), kept {skipped} existing file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
