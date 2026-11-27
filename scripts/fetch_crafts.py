#!/usr/bin/env python3
"""Convert the Atlas Academy CN nice_equip export into crafts/<id>.json.

Each craft essence becomes one compact object:

    id, name, type, rarity, cost, atk, hp,
    skills[]  (name / icon / effect: base, max-limit and event-limited versions),
    assets    (chara_graph / faces / narrow_figure, source URLs)

`type` is the first Atlas `flags` entry (falling back to `flag`) with its first
letter upper-cased.  `atk` and `hp` are the max-level values.  Illustrations in
`script.maleImage` are appended to the normal asset lists.  Existing files are
left untouched unless --overwrite is given, so a run only adds craft essences
that are not present.

Examples:
    python scripts/fetch_crafts.py --source nice_equip.json
    python scripts/fetch_crafts.py --source nice_equip.json --overwrite
    python scripts/fetch_crafts.py                      # downloads the export first
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRAFTS_DIR = ROOT / "crafts"
DEFAULT_URL = "https://api.atlasacademy.io/export/CN/nice_equip.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)
import dataset_assets  # noqa: E402  (local helper module)

ASSET_KEYS = {
    "chara_graph": "charaGraph",
    "faces": "faces",
    "narrow_figure": "equipFace",
}


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
        path = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "atlas_cn_nice_equip.json"
        if not path.is_file():
            download(args.url, path)
        else:
            print(f"using cached export: {path}")

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        fail(f"{path}: expected a non-empty JSON array")
    return data


def type_name(equip: dict) -> str:
    # Atlas leaves `flag` as "unknown" for some craft essences and only fills
    # the `flags` array; `normal` essences have an empty array.  Prefer flags.
    flags = equip.get("flags") or []
    value = str((flags[0] if flags else equip.get("flag")) or "unknown")
    return value[:1].upper() + value[1:]


def asset_urls(extra: dict, asset_key: str) -> list[str]:
    group = extra.get(asset_key) or {}
    # Some craft essences have no single composed image; Atlas only exposes the
    # tiles in imagePartsGroup (the `equip` URL for them returns 404).
    parts = group.get("imagePartsGroup") or {}
    if parts:
        return [url for _key, url in sorted(parts.items()) if url]
    equip = group.get("equip") or {}
    return [url for _key, url in sorted(equip.items()) if url]


def localize(url: object, sources: assets.AssetSources) -> str:
    return dataset_assets.localize(url, dataset_assets.CRAFT_RULES, sources)


def convert_skills(equip: dict, sources: assets.AssetSources) -> list[dict]:
    skills: list[dict] = []
    for skill in equip.get("skills") or []:
        name = str(skill.get("name") or "")
        icon_url = skill.get("icon")
        icon = localize(icon_url, sources)
        skills.append(
            {
                "name": name,
                "icon": icon,
                "effect": str(skill.get("detail") or ""),
            }
        )
        # Event-limited effects overwrite the (often "no effect") base skill;
        # keep them as adjacent entries with the same skill name.
        for group in skill.get("groupOverwrites") or []:
            skills.append(
                {
                    "name": name,
                    "icon": localize(group.get("icon") or icon_url, sources),
                    "effect": str(group.get("detail") or ""),
                }
            )
    return skills


def convert_assets(extra: dict, script: dict, sources: assets.AssetSources) -> dict:
    result: dict[str, list[str]] = {}
    male = script.get("maleImage") or {}
    for field, asset_key in ASSET_KEYS.items():
        urls = asset_urls(extra, asset_key)
        # Some Valentine craft essences ship a separate illustration for the
        # male Master in script.maleImage instead of extraAssets.
        for url in asset_urls(male, asset_key):
            if url not in urls:
                urls.append(url)
        result[field] = [localize(url, sources) for url in urls]
    return result


def convert_craft(equip: dict, sources: assets.AssetSources) -> dict:
    extra = equip.get("extraAssets") or {}
    script = equip.get("script") or {}
    return {
        "id": int(equip["id"]),
        "name": str(equip.get("name") or ""),
        "type": type_name(equip),
        "rarity": int(equip.get("rarity") or 0),
        "cost": int(equip.get("cost") or 0),
        "atk": int(equip.get("atkMax") if equip.get("atkMax") is not None else equip.get("atkBase") or 0),
        "hp": int(equip.get("hpMax") if equip.get("hpMax") is not None else equip.get("hpBase") or 0),
        "skills": convert_skills(equip, sources),
        "assets": convert_assets(extra, script, sources),
    }


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="local nice_equip.json (skip downloading)")
    parser.add_argument("--cache", help="where to cache the downloaded export")
    parser.add_argument("--url", default=DEFAULT_URL, help="export URL")
    parser.add_argument("--out-dir", type=Path, default=CRAFTS_DIR)
    parser.add_argument("--ids", nargs="*", type=int, help="only convert these craft ids")
    parser.add_argument("--overwrite", action="store_true", help="replace existing craft files")
    args = parser.parse_args()

    data = load_export(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sources = assets.AssetSources.load()

    wanted = set(args.ids) if args.ids else None
    written = 0
    skipped = 0
    try:
        for equip in data:
            craft_id = equip.get("id")
            if craft_id is None or (wanted is not None and craft_id not in wanted):
                continue
            path = args.out_dir / f"{craft_id}.json"
            if path.exists() and not args.overwrite:
                skipped += 1
                continue
            write_json(path, convert_craft(equip, sources))
            written += 1
    finally:
        sources.save()

    print(f"wrote {written} craft file(s), kept {skipped} existing file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
