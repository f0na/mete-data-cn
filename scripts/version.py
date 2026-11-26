#!/usr/bin/env python3
"""Parse and validate release tags of the form data-YYYY.MM.DD[.NNN].

A base release uses `data-YYYY.MM.DD`; patch releases append a three-digit
sequence (`data-YYYY.MM.DD.001`).  `revision` is a single comparable integer
derived from both parts, which keeps incremental-update lookups simple.

Usage:
    python scripts/version.py --tag data-2026.11.26.001 --check-base --json
    python scripts/version.py --self-test
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^data-(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d{3}))?$")


@dataclass(frozen=True)
class Version:
    tag: str
    year: int
    month: int
    day: int
    patch: int

    @property
    def base(self) -> str:
        return f"{self.year:04d}.{self.month:02d}.{self.day:02d}"

    @property
    def base_tag(self) -> str:
        return f"data-{self.base}"

    @property
    def revision(self) -> int:
        return int(f"{self.year:04d}{self.month:02d}{self.day:02d}") * 1000 + self.patch

    def as_manifest(self) -> dict:
        return {"base": self.base, "patch": self.patch, "revision": self.revision}


def parse_tag(tag: str, *, strict: bool = True) -> Version | None:
    """Return a Version for a release tag, or None when strict=False and invalid."""
    match = TAG_RE.fullmatch(tag)
    if not match:
        if strict:
            raise ValueError(
                f"invalid release tag {tag!r}: expected data-YYYY.MM.DD[.NNN]"
            )
        return None

    year, month, day = (int(match.group(index)) for index in (1, 2, 3))
    patch = int(match.group(4)) if match.group(4) is not None else 0

    try:
        date(year, month, day)
    except ValueError as exc:
        if strict:
            raise ValueError(f"invalid date in release tag {tag!r}: {exc}") from exc
        return None

    if match.group(4) is not None and patch == 0:
        if strict:
            raise ValueError(
                f"invalid release tag {tag!r}: patch number must start at 001"
            )
        return None

    return Version(tag=tag, year=year, month=month, day=day, patch=patch)


def base_tag_exists(version: Version, repo: Path = ROOT) -> bool:
    """Whether the base tag of a patch release exists locally."""
    if version.patch == 0:
        return True
    ref = f"refs/tags/{version.base_tag}"
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def self_test(verbose: bool = False) -> int:
    valid = [
        ("data-2026.11.26", 0, 20261126000),
        ("data-2026.11.26.001", 1, 20261126001),
        ("data-2026.11.26.999", 999, 20261126999),
        ("data-2024.02.29", 0, 20240229000),
    ]
    invalid = [
        "data-2026.11.26.000",
        "data-2026.11.26.01",
        "data-2026.11.26.1000",
        "data-2026.02.30",
        "data-2026.13.01",
        "data-2026.00.10",
        "DATA-2026.11.26",
        "data-2026.11.26 ",
        "2026.11.26",
        "data-2026.1.5",
        "test",
    ]

    failures = 0
    for tag, patch, revision in valid:
        parsed = parse_tag(tag, strict=False)
        if parsed is None or parsed.patch != patch or parsed.revision != revision:
            failures += 1
            print(f"FAIL valid case: {tag}")
        elif verbose:
            print(f"ok: {tag} -> patch={patch} revision={revision}")

    for tag in invalid:
        if parse_tag(tag, strict=False) is not None:
            failures += 1
            print(f"FAIL invalid case: {tag}")
        elif verbose:
            print(f"ok rejected: {tag}")

    if failures:
        print(f"{failures} version test(s) failed", file=sys.stderr)
        return 1
    print("version tests passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="release tag to parse")
    parser.add_argument("--check-base", action="store_true", help="require the base tag to exist")
    parser.add_argument("--json", action="store_true", help="print a JSON object")
    parser.add_argument("--self-test", action="store_true", help="run built-in cases")
    parser.add_argument("--verbose", action="store_true", help="print every self-test case")
    args = parser.parse_args()

    if args.self_test:
        return self_test(args.verbose)

    if not args.tag:
        parser.error("--tag is required unless --self-test is used")

    try:
        version = parse_tag(args.tag)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    assert version is not None

    if args.check_base and not base_tag_exists(version):
        print(
            f"error: base tag {version.base_tag!r} does not exist; "
            "push the base release before its patch releases",
            file=sys.stderr,
        )
        return 1

    payload = {
        "version": version.tag,
        "base": version.base,
        "base_tag": version.base_tag,
        "patch": version.patch,
        "revision": version.revision,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{version.tag}: base={version.base} patch={version.patch} "
            f"revision={version.revision}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
