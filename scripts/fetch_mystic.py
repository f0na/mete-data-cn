#!/usr/bin/env python3
"""Convert the Atlas Academy CN nice_mystic_code export into mystic/<id>.json.

Each mystic code becomes one object:

    id, name, shortName,
    skills[]  (name / icon / effect / cool_down / target / effects),
    assets    (item and costume images per Master gender)

Skill `effects` use the same shape as servant skills and are built with the
helpers from scripts/fetch.py.  Existing files are left untouched unless
--overwrite is given, so a run only adds mystic codes that are not present.

Examples:
    python scripts/fetch_mystic.py --source nice_mystic_code.json
    python scripts/fetch_mystic.py --source nice_mystic_code.json --overwrite
    python scripts/fetch_mystic.py                      # downloads the export first
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MYSTIC_DIR = ROOT / "mystic"
DEFAULT_URL = "https://api.atlasacademy.io/export/CN/nice_mystic_code.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)
import dataset_assets  # noqa: E402  (local helper module)
import fetch  # noqa: E402  (local helper module, shared effect conversion)


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
        path = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "atlas_cn_nice_mystic_code.json"
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
    return dataset_assets.localize(url, dataset_assets.MYSTIC_RULES, sources)


def convert_skill(skill: dict, sources: assets.AssetSources) -> dict:
    detail = fetch.clean_atlas_text(skill.get("detail"))
    effects = fetch.convert_effects(detail, skill.get("functions") or [])
    cool_down: list[int] = []
    for value in skill.get("coolDown") or []:
        if isinstance(value, int) and value > 0 and value not in cool_down:
            cool_down.append(value)
    return {
        "name": str(skill.get("name") or ""),
        "icon": localize(skill.get("icon"), sources),
        "effect": detail,
        "cool_down": cool_down,
        "target": fetch.effect_target(effects),
        "effects": effects,
    }


def gender_assets(extra: dict, asset_key: str, sources: assets.AssetSources) -> dict[str, str]:
    return {
        key: localize(value, sources)
        for key, value in (extra.get(asset_key) or {}).items()
        if value
    }


def convert_mystic(code: dict, sources: assets.AssetSources) -> dict:
    extra = code.get("extraAssets") or {}
    costumes = code.get("costumes") or []
    costume_extra = (costumes[0].get("extraAssets") if costumes else None) or extra
    return {
        "id": int(code["id"]),
        "name": str(code.get("name") or ""),
        "shortName": str(code.get("shortName") or ""),
        "skills": [convert_skill(skill, sources) for skill in code.get("skills") or []],
        "assets": {
            "item": gender_assets(extra, "item", sources),
            "costumes": gender_assets(costume_extra, "item", sources),
        },
    }


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="local nice_mystic_code.json (skip downloading)")
    parser.add_argument("--cache", help="where to cache the downloaded export")
    parser.add_argument("--url", default=DEFAULT_URL, help="export URL")
    parser.add_argument("--out-dir", type=Path, default=MYSTIC_DIR)
    parser.add_argument("--ids", nargs="*", type=int, help="only convert these mystic code ids")
    parser.add_argument("--overwrite", action="store_true", help="replace existing mystic code files")
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
            write_json(path, convert_mystic(code, sources))
            written += 1
    finally:
        sources.save()

    print(f"wrote {written} mystic code file(s), kept {skipped} existing file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
