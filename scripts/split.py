#!/usr/bin/env python3
"""One-off: split a merged servant.json (top-level array) into servants/<id>.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "servant.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "servants")
    parser.add_argument("--keep-source", action="store_true")
    args = parser.parse_args()

    with args.source.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list) or not data:
        raise SystemExit(f"error: {args.source} must contain a non-empty array")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    seen: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            raise SystemExit("error: every array item must be an object")
        sid = item.get("id")
        if not isinstance(sid, int) or isinstance(sid, bool) or sid <= 0:
            raise SystemExit(f"error: invalid servant id {sid!r}")
        if sid in seen:
            raise SystemExit(f"error: duplicate servant id {sid}")
        seen.add(sid)
        write_json(args.out_dir / f"{sid}.json", item)
        print(f"wrote {args.out_dir / f'{sid}.json'}")

    # Re-read the split files and verify they reproduce the source data.
    rebuilt = []
    for path in sorted(args.out_dir.glob("*.json"), key=lambda p: int(p.stem)):
        with path.open(encoding="utf-8") as f:
            rebuilt.append(json.load(f))

    expected = sorted(data, key=lambda item: item["id"])
    if rebuilt != expected:
        raise SystemExit("error: round-trip verification failed")

    ids = ", ".join(str(item["id"]) for item in rebuilt)
    print(f"Verified {len(rebuilt)} servant(s): {ids}")

    if not args.keep_source:
        args.source.unlink()
        print(f"Removed source file: {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
