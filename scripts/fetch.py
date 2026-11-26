#!/usr/bin/env python3
"""Convert the Atlas Academy CN nice_servant_lore export into servants/<id>.json.

The exporter reads Atlas' NiceServant objects and emits this repository's
compact Servant schema.  Skill, class-skill and noble-phantasm values, plus the
per-ascension skill/NP assignment, come from Mooncell (fgo.wiki); Atlas' export
repeats the base value for Over Charge effects and merges alternate forms.
Existing files are left untouched unless --overwrite is given, so running the
script only adds servants that are not present yet.

Examples:
    python scripts/fetch.py --source nice_servant_lore.json
    python scripts/fetch.py --source nice_servant_lore.json --overwrite
    python scripts/fetch.py --source nice_servant_lore.json --no-mooncell
    python scripts/fetch.py --source nice_servant_lore.json --no-assets
    python scripts/fetch.py                      # downloads the export first

Images are downloaded into images/ (not committed) and JSON stores paths
relative to the release package's images/ root.  Pass --no-assets to skip the
download and only store the paths.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVANTS_DIR = ROOT / "servants"
DEFAULT_URL = "https://api.atlasacademy.io/export/CN/nice_servant_lore.json"
ASSET_JOBS = 16

sys.path.insert(0, str(Path(__file__).resolve().parent))
import assets  # noqa: E402  (local helper module)
import mooncell  # noqa: E402  (local helper module)

CLASS_MAP = {
    "saber": "Saber",
    "archer": "Archer",
    "lancer": "Lancer",
    "rider": "Rider",
    "caster": "Caster",
    "assassin": "Assassin",
    "berserker": "Berserker",
    "shielder": "Shielder",
    "ruler": "Ruler",
    "avenger": "Avenger",
    "moonCancer": "MoonCancer",
    "alterEgo": "Alterego",
    "foreigner": "Foreigner",
    "pretender": "Pretender",
    "beast": "BeastDraco",
    "beastEresh": "BeastEresh",
    "unBeastOlgaMarie": "UnBeast",
}

CARD_MAP = {"1": "Arts", "2": "Buster", "3": "Quick"}
GENDER_MAP = {"male": "Male", "female": "Female", "unknown": "Unknown"}
ATTR_MAP = {"sky": "Sky", "earth": "Earth", "human": "Human", "star": "Star", "beast": "Beast"}

ATTR1_MAP = {
    "alignmentLawful": "Order",
    "alignmentChaotic": "Chaos",
    "alignmentNeutral": "Neutral",
    "alignmentBalanced": "Neutral",
}
ATTR2_MAP = {
    "alignmentGood": "Good",
    "alignmentEvil": "Evil",
    "alignmentBalanced": "Mean",
    "alignmentMadness": "Crazy",
    "alignmentSummer": "Summer",
    "alignmentBride": "Bride",
}
# Preferred order when a servant has more than one second-axis alignment.
ATTR2_PRIORITY = [
    "alignmentSummer",
    "alignmentBride",
    "alignmentMadness",
    "alignmentEvil",
    "alignmentBalanced",
    "alignmentGood",
]

TARGET_MAP = {
    "self": "SelfOnly",
    "commandTypeSelfTreasureDevice": "SelfOnly",
    "ptOne": "One",
    "ptOneHpLowestRate": "One",
    "ptRandom": "One",
    "enemyOne": "Enemy",
    "enemy": "Enemy",
    "enemyAll": "Enemy",
    "enemyFull": "Enemy",
    "allEnemy": "Enemy",
    "ptAll": "All",
    "ptFull": "All",
    "all": "All",
    "ptOther": "Other",
    "ptOtherFull": "Other",
    "ptSelfAnotherFirst": "Other",
    "fieldOther": "Other",
    "noTarget": "Other",
    "ptOneOther": "AllBeyondTarget",
}

# Functions that carry no displayable effect.
SKIP_FUNCS = {
    "hastenNpturn",
    "delayNpturn",
    "shortenSkill",
    "extendBuffturn",
    "shortenBuffcount",
    "cardReset",
    "transformServant",
}

# Buff / function values that are absolute amounts rather than percentages.
FLAT_FUNCS = {
    "gainStar",
    "gainHp",
    "gainHpPer",
    "lossHp",
    "lossHpSafe",
    "lossHpPerSafe",
    "lossStar",
}
FLAT_BUFFS = {
    "subSelfdamage",
    "addSelfdamage",
    "addDamage",
    "regainHp",
    "regainStar",
    "reduceHp",
    "guts",
    "addMaxhp",
    "subMaxhp",
}
# Buffs whose numeric svals are internal counters, not displayed values.
NO_VALUE_BUFFS = {"shortenSkillAfterUseSkill"}
# Values at or above this are internal ids (buff ids, svt ids, ...).
INTERNAL_VALUE_THRESHOLD = 100_000

ASSET_KEYS = {
    "chara_graph": "charaGraph",
    "faces": "faces",
    "narrow_figure": "narrowFigure",
    "command": "commands",
    "status": "status",
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
        path = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "atlas_cn_nice_servant_lore.json"
        if not path.is_file():
            download(args.url, path)
        else:
            print(f"using cached export: {path}")

    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        fail(f"{path}: expected a non-empty JSON array")
    return data


def clean_atlas_text(text: object) -> str:
    """Remove Atlas placeholder artifacts such as `{{1:Value:m}}%`."""
    value = str(text or "")
    while re.search(r"\{\{[^{}]*\}\}", value):
        value = re.sub(r"\{\{[^{}]*\}\}", "", value)
    # A dangling "%" is left behind when the placeholder supplied the number.
    value = re.sub(r"(?<=[一-鿿])%", "", value)
    value = re.sub(r"\[\{\d+\}\]|\{\d+\}", "", value)
    return value.strip()


def split_detail(detail: str) -> list[str]:
    if not detail:
        return []
    parts = []
    current = ""
    depth = 0
    for char in detail:
        if char in "「『（(":
            depth += 1
        elif char in "」』）)":
            depth = max(0, depth - 1)
        if char in "＆＋+" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def alignment(traits: list[dict]) -> tuple[str, str]:
    names = {t.get("name") for t in traits}
    attr1 = "Neutral"
    for name in ATTR1_MAP:
        if name in names:
            attr1 = ATTR1_MAP[name]
            break
    attr2 = "Mean"
    for name in ATTR2_PRIORITY:
        if name in names:
            attr2 = ATTR2_MAP[name]
            break
    return attr1, attr2


FUNC_KEYWORDS = {
    "gainNp": ("宝具值", "NP"),
    "lossNp": ("宝具值", "NP"),
    "gainNpTargetSum": ("宝具值", "NP"),
    "gainNpIndividualSum": ("宝具值", "NP"),
    "gainNpBuffIndividualSum": ("宝具值", "NP"),
    "gainStar": ("暴击星",),
    "lossStar": ("暴击星",),
    "gainHp": ("生命值", "HP", "回复"),
    "gainHpPer": ("生命值", "HP", "回复"),
    "lossHp": ("生命值", "HP"),
    "lossHpSafe": ("生命值", "HP"),
    "lossHpPerSafe": ("生命值", "HP"),
    "subState": ("解除",),
}
DAMAGE_KEYWORDS = ("发动", "强大的", "超强大", "伤害")


def values_for_function(fn: dict) -> tuple[str, list[int]]:
    func_type = fn.get("funcType")
    buff_types = tuple(b.get("type") for b in fn.get("buffs") or [])
    raw_values = []
    for sval in fn.get("svals") or []:
        if not isinstance(sval, dict):
            continue
        if "Value" in sval:
            raw_values.append(sval["Value"])
        elif "RateCount" in sval:
            raw_values.append(sval["RateCount"])
    raw_values = [v for v in raw_values if isinstance(v, (int, float))]
    raw_values = [v for v in raw_values if abs(v) < INTERNAL_VALUE_THRESHOLD]

    if set(buff_types) & NO_VALUE_BUFFS:
        return "None", []
    if not raw_values:
        return "None", []
    if func_type in FLAT_FUNCS or set(buff_types) & FLAT_BUFFS:
        return "Int", [int(v) for v in raw_values]
    if func_type in {"gainNp", "lossNp", "gainNpTargetSum", "gainNpIndividualSum", "gainNpBuffIndividualSum"}:
        return "Percent", [int(v) for v in raw_values]
    return "Percent", [int(v * 10) for v in raw_values]


def score_function(segment: str, fn: dict) -> int:
    """How well a function matches a detail segment (higher is better)."""
    score = 0
    for buff in fn.get("buffs") or []:
        name = str(buff.get("name") or "")
        if not name:
            continue
        if name in segment:
            score = max(score, 100 + len(name))
        for length in (6, 4, 3):
            keyword = name[:length]
            if len(keyword) >= 2 and keyword in segment:
                score = max(score, 10 + length)
                break
    func_type = fn.get("funcType") or ""
    if func_type.startswith("damageNp"):
        for keyword in DAMAGE_KEYWORDS:
            if keyword in segment:
                score = max(score, 80)
    for keyword in FUNC_KEYWORDS.get(func_type, ()):
        if keyword in segment:
            score = max(score, 70)
    return score


def is_displayable(fn: dict) -> bool:
    if fn.get("buffs"):
        return True
    for sval in fn.get("svals") or []:
        if isinstance(sval, dict) and ("Value" in sval or "RateCount" in sval):
            return True
    return False


def explicit_target(text: str) -> str | None:
    text = re.sub(r"<[^>]*>", "", text)
    if "除自身以外" in text:
        return "Other"
    if "解除弱化状态" in text:
        return "All"
    if "解除强化状态" in text:
        return "Enemy"
    if "特攻状态" in text:
        return "SelfOnly"
    if text.startswith("自身") or text.startswith("付与自身"):
        return "SelfOnly"
    if "自身的" in text and not text.startswith(("敌方", "敌人")):
        return "SelfOnly"
    if "己方单体" in text:
        return "One"
    if "己方全体" in text or "我方全体" in text:
        return "All"
    if "敌方" in text or "敌人" in text or "特攻" in text or "即死" in text:
        return "Enemy"
    if "【负面效果】" in text:
        return "SelfOnly"
    if any(keyword in text for keyword in ("下降", "降低", "封印", "无法行动", "充能减少")):
        return "Enemy"
    return None


def infer_target(text: str) -> str:
    return explicit_target(text) or "Other"


def dedupe_effects(effects: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for effect in effects:
        key = (effect["effect"], effect["kind"], tuple(effect["values"]), effect["target"])
        if key in seen:
            continue
        seen.add(key)
        result.append(effect)
    return result


def convert_effects(detail: str, functions: list[dict]) -> list[dict]:
    """One effect per displayed segment; unused (hidden) functions are dropped."""
    segments = [clean_atlas_text(part) for part in split_detail(detail)]
    segments = [part for part in segments if part]
    candidates = [fn for fn in functions if fn.get("funcType") not in SKIP_FUNCS]

    # Assign the strongest matches first so a weak keyword hit cannot steal a
    # function that clearly belongs to a later segment.
    pairs = []
    for segment_index, segment in enumerate(segments):
        for function_index, fn in enumerate(candidates):
            score = score_function(segment, fn)
            if score > 0:
                pairs.append((score, segment_index, function_index))
    pairs.sort(reverse=True)

    assigned: dict[int, int] = {}
    used_functions: set[int] = set()
    for _score, segment_index, function_index in pairs:
        if segment_index in assigned or function_index in used_functions:
            continue
        assigned[segment_index] = function_index
        used_functions.add(function_index)

    # Segments without a keyword match take the next displayable function.
    for segment_index in range(len(segments)):
        if segment_index in assigned:
            continue
        for function_index, fn in enumerate(candidates):
            if function_index not in used_functions and is_displayable(fn):
                assigned[segment_index] = function_index
                used_functions.add(function_index)
                break

    effects: list[dict] = []
    for segment_index, segment in enumerate(segments):
        function_index = assigned.get(segment_index)
        if function_index is None:
            effects.append(
                {
                    "effect": segment,
                    "kind": "None",
                    "values": [],
                    "script": [],
                    "target": infer_target(segment),
                }
            )
            continue
        fn = candidates[function_index]
        kind, values = values_for_function(fn)
        effects.append(
            {
                "effect": segment,
                "kind": kind,
                "values": values,
                "script": [],
                "target": TARGET_MAP.get(fn.get("funcTargetType"), "Other"),
            }
        )
    return dedupe_effects(effects)


def effect_target(effects: list[dict]) -> str:
    return effects[0]["target"] if effects else "SelfOnly"


def convert_skill(skill: dict, slot: int | None = None, collapse_duplicates: bool = False) -> dict:
    detail = clean_atlas_text(skill.get("detail"))
    effects = convert_effects(detail, skill.get("functions") or [])
    if collapse_duplicates:
        # Class passives have no skill levels; Atlas still repeats the value
        # ten times.  Collapse those, but keep every level for active skills,
        # append skills and noble phantasms.
        for effect in effects:
            if effect["values"] and len(set(effect["values"])) == 1:
                effect["values"] = [effect["values"][0]]
    cool_down: list[int] = []
    for value in skill.get("coolDown") or []:
        if isinstance(value, int) and value > 0 and value not in cool_down:
            cool_down.append(value)
    result = {
        "slot": skill.get("num", 0) if slot is None else slot,
        "name": str(skill.get("name") or ""),
        "icon": str(skill.get("icon") or ""),
        "strength": 1 if (skill.get("priority") or 0) > 1 else 0,
        "cool_down": cool_down,
        "effect": detail,
        "effects": effects,
        "target": effect_target(effects),
    }
    return result


def convert_append_skill(skill: dict) -> dict:
    return convert_skill(skill, slot=0)


def normalize_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("／", "/").replace("・", "·")


def parse_mooncell_values(raw_values: list[str]) -> tuple[str, list[int]] | None:
    """Convert Mooncell value strings (e.g. "30%", "562.5%", "1000") to our scale."""
    if not raw_values:
        return None
    if any("*" in str(value) for value in raw_values):
        # Formula values such as "100%+10%*N" cannot be represented here.
        return None
    numbers: list[int] = []
    percent = False
    for raw in raw_values:
        text = str(raw).strip()
        if not text or text in {"∅", "-", "—", "？", "?"}:
            continue
        match = re.match(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
        if not match:
            continue
        number = float(match.group(0))
        if "%" in text:
            percent = True
            numbers.append(int(round(number * 100)))
        else:
            numbers.append(int(round(number)))
    if not numbers:
        return "None", []
    return ("Percent", numbers) if percent else ("Int", numbers)


TEXT_REPLACEMENTS = (
    ("OverCharge", "过量充能"),
    ("Over Charge", "过量充能"),
    ("HP", "生命值"),
    ("NP", "宝具值"),
    ("Quick", "迅"),
    ("Arts", "技"),
    ("Buster", "力"),
    ("▲", ""),
)


def clean_mooncell_text(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", str(text), flags=re.S)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    # Only strip known HTML tags; angle brackets also wrap effect conditions
    # such as "<Over Charge时效果提升>".
    text = re.sub(
        r"</?(?:ref|br|span|div|small|big|b|i|u|sup|sub|p|a|font|ruby|rt|rp|nowiki|center|blockquote)\b[^>]*>",
        "",
        text,
        flags=re.I,
    )

    def render(match: re.Match[str]) -> str:
        parts = match.group(1).split("|")
        positional = [part.strip() for part in parts[1:] if "=" not in part and part.strip()]
        # {{特攻|key|display|...}} -> prefer the display text.
        if len(positional) >= 2 and positional[1]:
            return positional[1]
        if positional:
            return positional[0]
        return parts[0].strip()

    pattern = re.compile(r"\{\{([^{}]*)\}\}")
    while pattern.search(text):
        text = pattern.sub(render, text)
    text = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    for source, target in TEXT_REPLACEMENTS:
        text = text.replace(source, target)
    return text.strip()


MATCH_REPLACEMENTS = (
    ("再充能", "充能"),
    ("回充", "充能"),
    ("充能减少", "减少充能"),
    ("小幅", "少量"),
)


def match_text(text: str) -> str:
    text = clean_mooncell_text(text)
    for source, target in MATCH_REPLACEMENTS:
        text = text.replace(source, target)
    return re.sub(r"[\s（）()〔〕\[\]<>《》·、，,。:：;；'\"“”‘’/\\\-—…&＆+＋%]", "", text)


def longest_common_substring(left: str, right: str) -> int:
    best = 0
    previous = [0] * (len(right) + 1)
    for i in range(1, len(left) + 1):
        current = [0] * (len(right) + 1)
        for j in range(1, len(right) + 1):
            if left[i - 1] == right[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best:
                    best = current[j]
        previous = current
    return best


def build_mooncell_effects(detail: str, effects: list[dict], mc_record: dict | None) -> list[dict]:
    """Rebuild NP effects from Mooncell, which has the real OC/level numbers."""
    if not mc_record:
        return effects
    mc_effects = mc_record.get("effects") or []
    if not mc_effects:
        return effects

    segments = split_detail(detail)
    normalized_segments = [match_text(segment) for segment in segments]

    # Greedily assign the highest-overlap pairs first, so a weak match cannot
    # steal a segment that belongs to a later effect.
    pairs = []
    for mc_index, mc_effect in enumerate(mc_effects):
        if any("*" in str(value) for value in mc_effect.get("values") or []):
            # Formula effects cannot be represented as a numeric array; let
            # the Atlas value/text for that segment win instead.
            continue
        normalized = match_text(mc_effect.get("text") or "")
        for segment_index, segment in enumerate(normalized_segments):
            score = longest_common_substring(normalized, segment)
            if score >= 5:
                pairs.append((score, mc_index, segment_index))
    pairs.sort(reverse=True)
    assigned: dict[int, int] = {}
    used_segments: set[int] = set()
    for _score, mc_index, segment_index in pairs:
        if mc_index in assigned or segment_index in used_segments:
            continue
        assigned[mc_index] = segment_index
        used_segments.add(segment_index)

    result: list[dict] = []
    for mc_index, mc_effect in enumerate(mc_effects):
        segment_index = assigned.get(mc_index)
        if segment_index is not None:
            text = segments[segment_index]
            base = effects[segment_index] if segment_index < len(effects) else None
        else:
            text = clean_mooncell_text(mc_effect.get("text") or "")
            base = None

        parsed = parse_mooncell_values(mc_effect.get("values") or [])
        if parsed is None:
            if base is not None:
                result.append(base)
            continue
        kind, values = parsed
        target = explicit_target(text) or (base["target"] if base else "Other")
        result.append(
            {
                "effect": text,
                "kind": kind,
                "values": values,
                "script": [],
                "target": target,
            }
        )

    # Keep Atlas effects for segments Mooncell did not describe, but skip
    # leftovers that merely repeat an effect Mooncell already provided.
    for index, effect in enumerate(effects):
        if index in used_segments:
            continue
        normalized = match_text(effect["effect"])
        if any(longest_common_substring(normalized, match_text(item["effect"])) >= 4 for item in result):
            continue
        result.append(effect)
    return dedupe_effects(result)


def convert_noble(noble: dict, mc_record: dict | None = None) -> dict:
    detail = clean_atlas_text(noble.get("detail"))
    effects = convert_effects(detail, noble.get("functions") or [])
    effects = build_mooncell_effects(detail, effects, mc_record)
    return {
        "name": str(noble.get("name") or ""),
        "icon": str(noble.get("icon") or ""),
        "card": CARD_MAP.get(str(noble.get("card")), "Arts"),
        "rank": str(noble.get("rank") or ""),
        "type": str(noble.get("type") or ""),
        "strength": 1 if noble.get("strengthStatus") == 99 else 0,
        "effect": detail,
        "effects": effects,
    }


def pick_asset(assets: dict, category: str, key: str, fallback_key: str | None) -> str:
    values = assets.get(category) or {}
    if key in values and values[key]:
        return values[key]
    if fallback_key and fallback_key in values and values[fallback_key]:
        return values[fallback_key]
    # Fall back to the highest available ascension stage.
    numeric = sorted((int(k) for k in values if str(k).isdigit()), reverse=True)
    if numeric:
        for candidate in numeric:
            if str(candidate) in values and values[str(candidate)]:
                return values[str(candidate)]
    return ""


def form_traits(servant: dict, category: str, key: str) -> list[dict]:
    add = servant.get("ascensionAdd") or {}
    per_form = ((add.get("individuality") or {}).get(category) or {})
    traits = per_form.get(key)
    if traits:
        return traits
    return servant.get("traits") or []


def form_attribute(servant: dict, category: str, key: str) -> str:
    add = servant.get("ascensionAdd") or {}
    per_form = ((add.get("attribute") or {}).get(category) or {})
    return per_form.get(key) or servant.get("attribute") or "earth"


def form_name(servant: dict, field: str, category: str, key: str, default: str) -> str:
    add = servant.get("ascensionAdd") or {}
    value = ((add.get(field) or {}).get(category) or {}).get(key)
    return str(value) if value else default


def form_rarity(servant: dict, category: str, key: str) -> int:
    add = servant.get("ascensionAdd") or {}
    value = ((add.get("rarity") or {}).get(category) or {}).get(key)
    return int(value) if isinstance(value, int) else int(servant.get("rarity") or 0)


def form_cost(servant: dict, category: str, key: str, costume_id: int | None) -> int:
    add = servant.get("ascensionAdd") or {}
    lookup_key = str(costume_id) if costume_id is not None else key
    value = ((add.get("overwriteCost") or {}).get(category) or {}).get(lookup_key)
    return int(value) if isinstance(value, int) else int(servant.get("cost") or 0)


def form_overwrite_rarity(servant: dict, costume_id: int) -> int | None:
    add = servant.get("ascensionAdd") or {}
    value = ((add.get("overwriteRarity") or {}).get("costume") or {}).get(str(costume_id))
    return int(value) if isinstance(value, int) else None


def unlock_stage(skill: dict) -> int:
    """Ascension stage (1-4) in which Atlas says the skill becomes available."""
    cond = skill.get("condLimitCount")
    if not isinstance(cond, int) or cond <= 0:
        return 1
    # A few launch servants use condLimitCount 4 for their final-ascension
    # third skill; clamp to the last stage instead of dropping the skill.
    return min(cond + 1, 4)


def available_skills(servant: dict, stage: int | None) -> list[dict]:
    skills = []
    seen = set()
    for skill in servant.get("skills") or []:
        if stage is not None and unlock_stage(skill) > stage:
            continue
        key = (skill.get("num"), skill.get("name"), skill.get("icon"))
        if key in seen:
            continue
        seen.add(key)
        skills.append(convert_skill(skill))
    return skills


def story_extra_passives(servant: dict) -> list[dict]:
    result = []
    seen = set()
    for passive in servant.get("extraPassive") or []:
        conds = passive.get("extraPassive") or []
        if not conds:
            continue
        if not any(c.get("eventId") == 0 and c.get("condQuestId") for c in conds):
            continue
        name = passive.get("name")
        if name in seen:
            continue
        seen.add(name)
        result.append(convert_skill(passive, slot=0, collapse_duplicates=True))
    return result


def costume_class_skills(servant: dict, profile_costume: dict, costume_id: int) -> list[dict]:
    add = servant.get("ascensionAdd") or {}
    skill_ids = ((add.get("overwriteClassPassive") or {}).get("costume") or {}).get(str(costume_id))
    if not skill_ids:
        return []
    by_id = {}
    for section in ("classPassive", "extraPassive"):
        for skill in servant.get(section) or []:
            by_id[skill.get("id")] = skill
    result = []
    seen = set()
    for skill_id in skill_ids:
        skill = by_id.get(skill_id)
        if not skill or skill.get("name") in seen:
            continue
        seen.add(skill.get("name"))
        result.append(convert_skill(skill, slot=0, collapse_duplicates=True))
    return result


def base_class_skills(servant: dict) -> list[dict]:
    result = []
    seen = set()
    for skill in servant.get("classPassive") or []:
        name = skill.get("name")
        if name in seen:
            continue
        seen.add(name)
        result.append(convert_skill(skill, slot=0, collapse_duplicates=True))
    for skill in story_extra_passives(servant):
        if skill["name"] in seen:
            continue
        seen.add(skill["name"])
        result.append(skill)
    return result


def pick_mooncell_noble(mc_records: list[dict] | None, noble: dict) -> dict | None:
    if not mc_records:
        return None
    key = normalize_name(noble.get("name"))
    matches = [record for record in mc_records if normalize_name(record.get("name")) == key]
    if not matches:
        unique = {normalize_name(record.get("name")) for record in mc_records}
        if len(unique) == 1:
            matches = mc_records
    if not matches:
        return None
    if len(matches) > 1:
        # Mooncell lists the base NP first and the strengthened one second.
        return matches[-1] if noble.get("strengthStatus") == 99 else matches[0]
    return matches[0]


def convert_nobles(servant: dict, mc_records: list[dict] | None = None) -> list[dict]:
    groups: dict[tuple[str, int], list[dict]] = {}
    order: list[tuple[str, int]] = []
    for noble in servant.get("noblePhantasms") or []:
        if noble.get("num") != 1:
            continue
        name = noble.get("name")
        if (
            not name
            or name == "？？？"
            or noble.get("rank") == "？"
            or noble.get("detail") == "不明"
        ):
            continue
        strength = 1 if noble.get("strengthStatus") == 99 else 0
        key = (normalize_name(name), strength)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(noble)

    nobles = []
    for key in order:
        # Keep both the base and strengthened versions of the same NP.
        noble = max(groups[key], key=lambda item: item.get("priority") or 0)
        nobles.append(convert_noble(noble, pick_mooncell_noble(mc_records, noble)))
    return nobles


TARGET_HINT_MAP = {
    "自身": "SelfOnly",
    "自己": "SelfOnly",
    "己方单体": "One",
    "己方全体": "All",
    "我方全体": "All",
    "敌方单体": "Enemy",
    "敌方全体": "Enemy",
    "全体": "All",
}


def target_from_hint(hint: object) -> str | None:
    if not hint:
        return None
    text = str(hint)
    for keyword, target in TARGET_HINT_MAP.items():
        if keyword in text:
            return target
    if "敌" in text:
        return "Enemy"
    return None


def atlas_skill_index(servant: dict) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for section in ("skills", "classPassive", "extraPassive"):
        for skill in servant.get(section) or []:
            index.setdefault(normalize_name(skill.get("name")), skill)
    return index


def atlas_noble_index(servant: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for noble in servant.get("noblePhantasms") or []:
        index.setdefault(normalize_name(noble.get("name")), []).append(noble)
    return index


def lookup_atlas_skill(index: dict[str, dict], name: object) -> dict | None:
    key = normalize_name(name)
    if key in index:
        return index[key]
    for candidate_key, skill in index.items():
        if candidate_key.startswith(key) or key.startswith(candidate_key):
            return skill
    return None


def lookup_atlas_noble(index: dict[str, list[dict]], name: object, strength: int | None = None) -> dict | None:
    key = normalize_name(name)
    matches = index.get(key)
    if not matches:
        for candidate_key, candidate in index.items():
            if candidate_key.startswith(key) or key.startswith(candidate_key):
                matches = candidate
                break
    if not matches:
        return None
    if strength is not None:
        for noble in matches:
            level = 1 if noble.get("strengthStatus") == 99 else 0
            if level == strength:
                return noble
    return matches[0]


def cooldowns_from_atlas(skill: dict | None, fallback_cd: int = 0) -> list[int]:
    if skill:
        values = []
        for value in skill.get("coolDown") or []:
            if isinstance(value, int) and value > 0 and value not in values:
                values.append(value)
        if values:
            return values
    if fallback_cd <= 0:
        return []
    return [max(fallback_cd - offset, 0) for offset in range(3) if fallback_cd - offset > 0]


def parse_inline_values(text: str) -> tuple[str, list[int]]:
    percentages = re.findall(r"(-?\d+(?:\.\d+)?)\s*%", text)
    if percentages:
        return "Percent", [int(round(float(value) * 100)) for value in percentages]
    without_percent = re.sub(r"-?\d+(?:\.\d+)?\s*%", "", text)
    flat = re.findall(r"\((\d+)\)", without_percent)
    if flat:
        return "Int", [int(value) for value in flat]
    return "None", []


def mooncell_name(raw: dict) -> str:
    return clean_mooncell_text(raw.get("name") or "")


def convert_mooncell_skill(raw: dict, atlas_skill: dict | None) -> dict:
    effects = []
    for item in raw.get("effects") or []:
        text = clean_mooncell_text(item.get("text") or "")
        parsed = parse_mooncell_values(item.get("values") or [])
        kind, values = parsed if parsed is not None else ("None", [])
        target = target_from_hint(item.get("target_hint")) or explicit_target(text) or "SelfOnly"
        effects.append(
            {
                "effect": text,
                "kind": kind,
                "values": values,
                "script": [],
                "target": target,
            }
        )
    effects = dedupe_effects(effects)
    cooldown = cooldowns_from_atlas(atlas_skill, int(raw.get("cooldown") or 0))
    result = {
        "slot": int(raw.get("slot") or 0),
        "name": mooncell_name(raw),
        "icon": str((atlas_skill or {}).get("icon") or ""),
        "strength": int(raw.get("strength") or 0),
        "cool_down": cooldown,
        "effect": "＆".join(effect["effect"] for effect in effects),
        "effects": effects,
        "target": effect_target(effects) if effects else "SelfOnly",
    }
    if raw.get("switch_cond"):
        result["switch_cond"] = str(raw["switch_cond"])
    return result


def convert_mooncell_class_skill(raw: dict, atlas_skill: dict | None) -> dict:
    text = clean_mooncell_text(raw.get("effect") or "")
    clauses = [
        part.strip().replace("「", "").replace("」", "")
        for part in re.split(r"[＆＋+]", text)
        if part.strip()
    ] or [text]
    effects = []
    for clause in clauses:
        kind, values = parse_inline_values(clause)
        target = explicit_target(clause) or "SelfOnly"
        effects.append(
            {
                "effect": clause,
                "kind": kind,
                "values": values,
                "script": [],
                "target": target,
            }
        )
    effects = dedupe_effects(effects)
    return {
        "slot": 0,
        "name": mooncell_name(raw),
        "icon": str((atlas_skill or {}).get("icon") or ""),
        "strength": 0,
        "cool_down": [],
        "effect": text,
        "effects": effects,
        "target": effect_target(effects) if effects else "SelfOnly",
    }


def convert_mooncell_noble(raw: dict, atlas_noble: dict | None, atlas_effects: list[dict] | None = None) -> dict:
    effects = []
    for index, item in enumerate(raw.get("effects") or []):
        text = clean_mooncell_text(item.get("text") or "")
        parsed = parse_mooncell_values(item.get("values") or [])
        kind, values = parsed if parsed is not None else ("None", [])
        target = target_from_hint(item.get("target_hint")) or explicit_target(text)
        if target is None and atlas_effects and index < len(atlas_effects):
            target = atlas_effects[index]["target"]
        effects.append(
            {
                "effect": text,
                "kind": kind,
                "values": values,
                "script": [],
                "target": target or "Other",
            }
        )
    effects = dedupe_effects(effects)

    card = str(raw.get("card") or "").strip()
    card = card[:1].upper() + card[1:].lower() if card else ""
    if card not in {"Quick", "Arts", "Buster"}:
        card = CARD_MAP.get(str((atlas_noble or {}).get("card")), "Arts")

    result = {
        "name": mooncell_name(raw),
        "icon": str((atlas_noble or {}).get("icon") or ""),
        "card": card,
        "rank": str(raw.get("rank") or (atlas_noble or {}).get("rank") or ""),
        "type": str(raw.get("type") or (atlas_noble or {}).get("type") or ""),
        "strength": int(raw.get("strength") or 0),
        "effect": "＆".join(effect["effect"] for effect in effects),
        "effects": effects,
    }
    if raw.get("switch_cond"):
        result["switch_cond"] = str(raw["switch_cond"])
    return result


def mooncell_skills_for_stage(servant: dict, mc_data: dict, stage: int) -> list[dict] | None:
    forms = mc_data.get("skill_forms") or []
    form = next((item for item in forms if stage in item.get("stages", set())), None)
    if not form:
        return None
    atlas_index = atlas_skill_index(servant)
    result = []
    for raw in form.get("skills") or []:
        if int(raw.get("unlock_stage") or 1) > stage:
            continue
        if mooncell_name(raw) in {"", "？", "？？？"}:
            continue
        result.append(convert_mooncell_skill(raw, lookup_atlas_skill(atlas_index, mooncell_name(raw))))

    # Strengthened skills are sometimes newer than the CN client's skill list;
    # borrow the base skill icon so the UI still has an image.
    atlas_icons_by_slot = {}
    for skill in servant.get("skills") or []:
        icon = skill.get("icon")
        if icon:
            atlas_icons_by_slot.setdefault(skill.get("num"), icon)
    for skill in result:
        if skill["icon"]:
            continue
        for other in result:
            if other is not skill and other["slot"] == skill["slot"] and other["icon"]:
                skill["icon"] = other["icon"]
                break
        if not skill["icon"]:
            skill["icon"] = atlas_icons_by_slot.get(skill["slot"], "")

    deduped = {}
    for skill in result:
        key = (skill["slot"], skill["name"], skill["strength"], skill.get("switch_cond") or "")
        deduped[key] = skill
    return list(deduped.values()) or None


def mooncell_class_skills(servant: dict, mc_data: dict) -> list[dict] | None:
    raws = mc_data.get("class_skills") or []
    if not raws:
        return None
    atlas_index = atlas_skill_index(servant)
    atlas_class = servant.get("classPassive") or []
    result = []
    for index, raw in enumerate(raws):
        atlas_skill = lookup_atlas_skill(atlas_index, mooncell_name(raw))
        # Names occasionally differ between Mooncell and Atlas (e.g.
        # 灵基情报保存 vs 灵基信息保存); fall back to the same position.
        if atlas_skill is None and index < len(atlas_class):
            atlas_skill = atlas_class[index]
        result.append(convert_mooncell_class_skill(raw, atlas_skill))

    first_icon = next((skill["icon"] for skill in result if skill["icon"]), "")
    for skill in result:
        if not skill["icon"]:
            skill["icon"] = first_icon
    return result


def mooncell_nobles_for_stage(servant: dict, mc_data: dict, stage: int) -> list[dict] | None:
    forms = mc_data.get("noble_forms") or []
    form = next((item for item in forms if stage in item.get("stages", set())), None)
    if not form:
        return None

    groups: dict[tuple[str, str, int], list[dict]] = {}
    order: list[tuple[str, str, int]] = []
    for raw in form.get("nobles") or []:
        if int(raw.get("unlock_stage") or 1) > stage:
            continue
        if mooncell_name(raw) in {"", "？", "？？？"} or raw.get("rank") == "？" or raw.get("type") == "不明":
            continue
        name_key = normalize_name(raw.get("name"))
        if not name_key:
            continue
        strength = int(raw.get("strength") or 0)
        key = (name_key, str(raw.get("switch_cond") or ""), strength)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(raw)
    if not order:
        return None

    atlas_index = atlas_noble_index(servant)
    result = []
    for key in order:
        raw = groups[key][0]
        atlas_noble = lookup_atlas_noble(atlas_index, mooncell_name(raw), int(raw.get("strength") or 0))
        atlas_effects = None
        if atlas_noble:
            atlas_effects = convert_effects(
                str(atlas_noble.get("detail") or ""), atlas_noble.get("functions") or []
            )
        result.append(convert_mooncell_noble(raw, atlas_noble, atlas_effects))
    return result or None


def build_spirit(
    servant: dict,
    label: str,
    category: str,
    key: str,
    stage: int | None,
    mc_data: dict | None = None,
) -> dict:
    costume = None
    if category == "costume":
        costume = (servant.get("profile") or {}).get("costume", {}).get(key)
    costume_id = costume.get("id") if costume else None

    traits = form_traits(servant, category, key)
    attr1, attr2 = alignment(traits)
    sub_attr = ATTR_MAP.get(str(form_attribute(servant, category, key)), "Earth")

    rarity = form_rarity(servant, category, key)
    if category == "costume" and costume_id is not None:
        override = form_overwrite_rarity(servant, costume_id)
        if override is not None:
            rarity = override

    fallback_key = None if category == "ascension" else "4"
    extra = servant.get("extraAssets") or {}
    assets = {}
    for field, asset_key in ASSET_KEYS.items():
        assets[field] = pick_asset(extra.get(asset_key) or {}, category, key, fallback_key)

    # Costumes share the final ascension's battle kit unless the game says
    # otherwise; Mooncell does not publish separate costume skill tables.
    effective_stage = stage if stage is not None else 4
    skills = None
    class_skills = None
    nobles = None
    if mc_data:
        skills = mooncell_skills_for_stage(servant, mc_data, effective_stage)
        class_skills = mooncell_class_skills(servant, mc_data)
        nobles = mooncell_nobles_for_stage(servant, mc_data, effective_stage)
    if skills is None:
        skills = available_skills(servant, stage)
    if class_skills is None:
        class_skills = base_class_skills(servant)
    if nobles is None:
        nobles = convert_nobles(servant)
    if costume_id is not None:
        for skill in costume_class_skills(servant, costume, costume_id):
            if skill["name"] not in {s["name"] for s in class_skills}:
                class_skills.append(skill)

    return {
        "spirit": label,
        "name": form_name(servant, "overWriteServantName", category, key, str(servant.get("name") or "")),
        "battle_name": form_name(
            servant, "overWriteServantBattleName", category, key, str(servant.get("battleName") or "")
        ),
        "gender": GENDER_MAP.get(str(servant.get("gender")), "Unknown"),
        "attr1": attr1,
        "attr2": attr2,
        "sub_attr": sub_attr,
        "cost": form_cost(servant, category, key, costume_id),
        "rarity": rarity,
        "skills": skills,
        "class_skills": class_skills,
        "nobles": nobles,
        "assets": assets,
    }


def is_supported(servant: dict) -> bool:
    if servant.get("type") not in {"normal", "heroine"}:
        return False
    if not isinstance(servant.get("collectionNo"), int) or servant.get("collectionNo") <= 0:
        return False
    if str(servant.get("className")) not in CLASS_MAP:
        return False
    if servant.get("flag") not in {"normal", "ignoreCombineLimitSpecial"}:
        return False
    return True


def convert_servant(servant: dict, mc_data: dict | None = None) -> dict:
    extra = servant.get("extraAssets") or {}
    ascensions = sorted((int(k) for k in ((extra.get("faces") or {}).get("ascension") or {}) if str(k).isdigit()))
    costumes = sorted(
        k
        for k in ((extra.get("faces") or {}).get("costume") or {})
        if (servant.get("profile") or {}).get("costume", {}).get(k)
        and (servant["profile"]["costume"][k].get("costumeCollectionNo") or 0) > 0
    )

    spirits = [
        build_spirit(servant, f"第{stage}阶段", "ascension", str(stage), stage, mc_data)
        for stage in ascensions
    ]
    for key in costumes:
        profile_costume = servant["profile"]["costume"][key]
        label = profile_costume.get("shortName") or profile_costume.get("name") or key
        spirits.append(build_spirit(servant, str(label), "costume", key, None, mc_data))

    if not spirits:
        # No ascension assets: still emit a single spirit so the servant is usable.
        spirits.append(build_spirit(servant, "第1阶段", "ascension", "1", 1, mc_data))

    append_skills = []
    for entry in servant.get("appendPassive") or []:
        skill = entry.get("skill")
        if skill:
            append_skills.append(convert_append_skill(skill))

    return {
        "id": int(servant["id"]),
        "no": int(servant["collectionNo"]),
        "class": CLASS_MAP[str(servant["className"])],
        "cards": [CARD_MAP.get(str(card), "Arts") for card in servant.get("cards") or []],
        "append_skills": append_skills,
        "spirits": spirits,
    }


def write_json(path: Path, obj: object) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=4, ensure_ascii=False)
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="local nice_servant_lore.json (skip downloading)")
    parser.add_argument("--cache", help="where to cache the downloaded export")
    parser.add_argument("--url", default=DEFAULT_URL, help="export URL")
    parser.add_argument("--out-dir", type=Path, default=SERVANTS_DIR)
    parser.add_argument("--ids", nargs="*", type=int, help="only convert these servant ids")
    parser.add_argument("--overwrite", action="store_true", help="replace existing servant files")
    parser.add_argument(
        "--mooncell-cache",
        type=Path,
        default=Path(tempfile.gettempdir()) / "mete-mooncell",
        help="Mooncell page cache directory",
    )
    parser.add_argument("--no-mooncell", action="store_true", help="keep Atlas values for NP effects")
    parser.add_argument("--refresh-mooncell", action="store_true", help="refetch cached Mooncell pages")
    parser.add_argument("--no-assets", action="store_true", help="store asset paths without downloading images")
    args = parser.parse_args()

    data = load_export(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    wanted = set(args.ids) if args.ids else None
    targets = []
    skipped = 0
    for servant in data:
        sid = servant.get("id")
        if wanted is not None and sid not in wanted:
            continue
        if not is_supported(servant):
            continue
        path = args.out_dir / f"{sid}.json"
        if path.exists() and not args.overwrite:
            skipped += 1
            continue
        targets.append(servant)

    mc_index: dict[int, list[dict]] = {}
    if targets and not args.no_mooncell:
        print(f"loading Mooncell data for {len(targets)} servant(s) ...")
        try:
            mc_index = mooncell.build_index(
                args.mooncell_cache,
                [int(servant["collectionNo"]) for servant in targets],
                refresh=args.refresh_mooncell,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to Atlas values
            print(f"warning: Mooncell unavailable ({exc}); using Atlas values")

    converted = [
        (servant, convert_servant(servant, mc_index.get(int(servant["collectionNo"]))))
        for servant in targets
    ]

    refs: list[str] = []
    seen_refs: set[str] = set()
    for _servant, data in converted:
        assets.collect(data, refs, seen_refs)
    if refs and not args.no_assets:
        assets.download_many(refs, ASSET_JOBS)

    for servant, data in converted:
        write_json(args.out_dir / f"{servant['id']}.json", assets.rewrite(data))

    print(f"wrote {len(targets)} servant file(s), kept {skipped} existing file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
