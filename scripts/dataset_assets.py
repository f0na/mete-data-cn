"""Map Atlas CN asset URLs to per-dataset local paths under assets/.

Each dataset owns its own asset root so the release can ship one resource
package per dataset without overlapping entries:

    Craft/...        craft essences and their skill icons
    Mystic/...       mystic codes and their skill icons
    Cmdcodes/...     command codes and their skill icons

Servant assets keep their existing `Servant/` + `SkillIcons/` layout.
"""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

ATLAS_HOST = "static.atlasacademy.io"

CRAFT_RULES = (
    ("CN/CharaGraph/", "Craft/CharaGraph/"),
    ("CN/Faces/", "Craft/Faces/"),
    ("CN/EquipFaces/", "Craft/EquipFaces/"),
    ("CN/SkillIcons/", "Craft/SkillIcons/"),
)
MYSTIC_RULES = (
    ("CN/Items/", "Mystic/Items/"),
    ("CN/SkillIcons/", "Mystic/SkillIcons/"),
)
CMDCODE_RULES = (
    ("CN/CommandGraph/", "Cmdcodes/CommandGraph/"),
    ("CN/CommandCodes/", "Cmdcodes/CommandCodes/"),
    ("CN/SkillIcons/", "Cmdcodes/SkillIcons/"),
)


def localize(url: object, rules: tuple[tuple[str, str], ...], sources=None) -> str:
    """Convert an Atlas URL to its local asset path and record the source."""
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if parsed.netloc != ATLAS_HOST:
        raise ValueError(f"unexpected asset host: {text}")
    path = unquote(parsed.path).lstrip("/")
    for prefix, local_prefix in rules:
        if path.startswith(prefix):
            rel = local_prefix + path[len(prefix) :]
            if sources is not None:
                sources.record(rel, text)
            return rel
    raise ValueError(f"unmapped asset URL: {text}")
