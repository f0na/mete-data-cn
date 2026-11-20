"""Fetch Mooncell (fgo.wiki) pages and parse noble phantasm values.

Atlas Academy's CN export repeats the base value for effects that scale with
Over Charge (and several other multi-level fields).  Mooncell's servant pages
carry the real per-level numbers, so fetch.py uses this module to override the
NP `effects[].values` arrays.

Pages are cached as `<cache-dir>/<collectionNo>.wiki`; the servant index is
cached as `<cache-dir>/servant_list.wiki`.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = "https://fgo.wiki/index.php"
LIST_TITLE = "英灵图鉴/数据"
USER_AGENT = "mete-data-cn/1.0"

EFFECT_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _fetch(title: str) -> str:
    url = API + "?" + urllib.parse.urlencode({"title": title, "action": "raw"})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001 - network errors are retried
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {title}: {last}")


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _find_templates(text: str, name: str) -> list[str]:
    results = []
    marker = "{{" + name
    index = 0
    while True:
        start = text.find(marker, index)
        if start < 0:
            break
        depth = 0
        i = start
        while i < len(text) - 1:
            pair = text[i : i + 2]
            if pair == "{{":
                depth += 1
                i += 2
            elif pair == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    break
            else:
                i += 1
        results.append(text[start:i])
        index = i
    return results


def _split_params(body: str) -> list[str]:
    parts = []
    current = ""
    curly = 0
    square = 0
    i = 0
    while i < len(body):
        pair = body[i : i + 2]
        if pair == "{{":
            curly += 1
            current += pair
            i += 2
        elif pair == "}}":
            curly -= 1
            current += pair
            i += 2
        elif pair == "[[":
            square += 1
            current += pair
            i += 2
        elif pair == "]]":
            square -= 1
            current += pair
            i += 2
        elif body[i] == "|" and curly == 0 and square == 0:
            parts.append(current)
            current = ""
            i += 1
        else:
            current += body[i]
            i += 1
    parts.append(current)
    return parts


def _parse_template(template: str) -> dict[str, str]:
    body = template[2:-2]
    params: dict[str, str] = {}
    for part in _split_params(body)[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            params.setdefault(key.strip(), value.strip())
    return params


def _parse_info_effects(info: str) -> list[dict]:
    """Parse the newer `宝具信息=` format:

        ;;effect text
        ::10%::15%::20%::25%::30%
        **对象##自身
    """
    effects: list[dict] = []
    pending_start = 0
    for line in info.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(";;"):
            effects.append({"text": line[2:].strip(), "values": []})
        elif line.startswith("::") and effects:
            values = [value.strip() for value in line[2:].split("::") if value.strip()]
            effects[-1]["values"] = values
        elif line.startswith("**对象##"):
            target = line.split("##", 1)[1].strip()
            for effect in effects[pending_start:]:
                effect["target_hint"] = target
            pending_start = len(effects)
    return effects


CHINESE_NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}


def _find_section(text: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    start = text.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    end = len(text)
    for marker in end_markers:
        index = text.find(marker, start)
        if 0 <= index < end:
            end = index
    return text[start:end]


def _parse_tabber_body(body: str) -> list[tuple[str, str]]:
    parts = re.split(r"(?m)^([^=\n<|{}\[;:]+?)=\s*", body)
    groups = []
    for index in range(1, len(parts), 2):
        label = parts[index].strip()
        content = parts[index + 1] if index + 1 < len(parts) else ""
        groups.append((label, content))
    return groups


def _extract_tabbers(section: str) -> tuple[str, list[dict]]:
    """Return (text outside all tabbers, [{start, groups}, ...])."""
    plain_parts = []
    tabbers = []
    position = 0
    for match in re.finditer(r"<tabber>(.*?)</tabber>", section, re.S):
        plain_parts.append(section[position : match.start()])
        groups = _parse_tabber_body(match.group(1))
        if groups:
            tabbers.append({"start": match.start(), "groups": groups})
        else:
            plain_parts.append(match.group(1))
        position = match.end()
    plain_parts.append(section[position:])
    return "".join(plain_parts), tabbers


def _tabber_split(section: str) -> tuple[str, list[tuple[str, str]] | None]:
    """Remove the first <tabber> block and return it as (label, content) groups."""
    start = section.find("<tabber>")
    if start < 0:
        return section, None
    end = section.find("</tabber>", start)
    if end < 0:
        return section, None
    body = section[start + len("<tabber>") : end]
    plain = section[:start] + section[end + len("</tabber>") :]
    # Labels can share a line with the content: `第1·第2阶段形象时={{宝具`.
    parts = re.split(r"(?m)^([^=\n<|{}\[;:]+?)=\s*", body)
    if len(parts) <= 1:
        # Not a recognisable tabber; keep the section intact.
        return section, None
    groups = []
    for index in range(1, len(parts), 2):
        label = parts[index].strip()
        content = parts[index + 1] if index + 1 < len(parts) else ""
        groups.append((label, content))
    return plain, groups or None


FORM_KEYWORDS = ("再临", "灵基", "阶段", "形象", "形态")


def _label_stages(label: str) -> set[int]:
    if "初始" in label:
        return {1}
    if not any(keyword in label for keyword in FORM_KEYWORDS):
        return set()
    numbers = [CHINESE_NUMBERS[ch] for ch in label if ch in CHINESE_NUMBERS]
    numbers += [int(ch) for ch in label if ch.isdigit()]
    if not numbers:
        return set()
    return {min(number + 1, 4) for number in numbers}


def _assign_form_stages(
    groups: list[tuple[str, str]] | None, fallback_content: str
) -> list[tuple[set[int], str]]:
    if not groups:
        return [({1, 2, 3, 4}, fallback_content)]

    stage_sets = [_label_stages(label) for label, _ in groups]
    if not any(stage_sets):
        # Labels such as "通常" / "超级青子时" are battle-form switches, not
        # ascension stages.  The first (normal) form is the one used for the
        # servant's ascension spirits.
        return [({1, 2, 3, 4}, groups[0][1])]

    filtered = [
        (stages, content)
        for stages, (_label, content) in zip(stage_sets, groups)
        if stages
    ]
    stage_sets = [stages for stages, _ in filtered]
    covered = set().union(*stage_sets)
    if 1 not in covered:
        stage_sets[0].add(1)
    covered = set().union(*stage_sets)
    for stage in range(1, 5):
        if stage in covered:
            continue
        previous = 0
        for index, stages in enumerate(stage_sets):
            if stages and min(stages) < stage:
                previous = index
        stage_sets[previous].add(stage)
    return list(zip(stage_sets, [content for _, content in filtered]))


def _switch_label(label: str) -> str | None:
    label = label.strip()
    return label or None


def _ignore_variant_label(label: str) -> bool:
    return any(keyword in label for keyword in ("限定", "NPC", "助战", "剧情"))


def _has_ascension_labels(groups: list[tuple[str, str]] | None) -> bool:
    return bool(groups) and any(_label_stages(label) for label, _ in groups)


def _starts_with_skill_header(content: str) -> bool:
    return bool(re.match(r"^\s*'''\s*技能\s*[0-9]", content))


def _last_skill_header(content: str) -> tuple[int, str] | None:
    blocks = _split_skill_blocks(content)
    if not blocks:
        return None
    slot, condition, _block = blocks[-1]
    return slot, condition


def _header_before(content: str, position: int) -> tuple[int, str] | None:
    pattern = re.compile(r"'''\s*技能\s*([0-9])\s*(?:[（(]([^）)]*)[）)])?\s*'''")
    matches = list(pattern.finditer(content[:position]))
    if not matches:
        return None
    match = matches[-1]
    return int(match.group(1)), match.group(2) or ""


def _split_skill_blocks(content: str) -> list[tuple[int, str, str]]:
    pattern = re.compile(r"'''\s*技能\s*([0-9])\s*(?:[（(]([^）)]*)[）)])?\s*'''")
    matches = list(pattern.finditer(content))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        blocks.append((int(match.group(1)), match.group(2) or "", content[start:end]))
    return blocks


def _strengthen_stage(block: str) -> int | None:
    match = re.search(r"达到灵基再临第\s*([一二三四1-4])\s*阶段", block)
    if not match:
        return None
    char = match.group(1)
    number = CHINESE_NUMBERS.get(char) or int(char)
    return min(number + 1, 4)


def _unlock_stage(condition: str, block: str) -> int:
    if "初期开放" in condition:
        return 1
    match = re.search(r"灵基再临第\s*([一二三四1-4])\s*阶段", condition)
    if not match:
        match = re.search(r"灵基再临第\s*([一二三四1-4])\s*阶段", block[:200])
    if match:
        char = match.group(1)
        number = CHINESE_NUMBERS.get(char) or int(char)
        return min(number + 1, 4)
    return 1


def _has_top_level_equals(part: str) -> bool:
    depth = 0
    in_tag = False
    index = 0
    while index < len(part):
        pair = part[index : index + 2]
        if pair == "{{":
            depth += 1
            index += 2
        elif pair == "}}":
            depth -= 1
            index += 2
        elif part[index] == "<":
            in_tag = True
            index += 1
        elif part[index] == ">":
            in_tag = False
            index += 1
        elif part[index] == "=" and depth == 0 and not in_tag:
            return True
        else:
            index += 1
    return False


def _positional_params(template: str) -> list[str]:
    body = template[2:-2]
    body = re.sub(r"<ref[^>]*>.*?</ref>", "", body, flags=re.S)
    body = re.sub(r"<ref[^>]*/>", "", body, flags=re.S)
    return [part.strip() for part in _split_params(body)[1:] if not _has_top_level_equals(part)]


def _parse_hold_skill(template: str, slot: int, unlock_stage: int, strength: int) -> dict | None:
    params = _positional_params(template)
    if len(params) < 4:
        return None
    name = params[1]
    cooldown_match = re.search(r"\d+", params[3])
    cooldown = int(cooldown_match.group()) if cooldown_match else 0
    rest = params[4:]
    effects = []
    for index in range(0, len(rest), 11):
        chunk = rest[index : index + 11]
        if not chunk or not chunk[0]:
            continue
        text = chunk[0]
        values = [value for value in chunk[1:11]]
        effects.append({"text": text, "values": values})
    if not effects:
        return None
    return {
        "name": name,
        "slot": slot,
        "unlock_stage": unlock_stage,
        "strength": strength,
        "cooldown": cooldown,
        "effects": effects,
    }


def _parse_skill_templates(
    content: str, slot: int, condition: str, switch_cond: str | None
) -> list[dict]:
    unlock = _unlock_stage(condition, content)
    strengthen_stage = _strengthen_stage(content)
    templates = _find_templates(content, "持有技能")
    strengthened = "强化信息" in content
    skills = []
    for index, template in enumerate(templates):
        strength = 1 if strengthened and index > 0 else 0
        skill_unlock = strengthen_stage if strength and strengthen_stage else unlock
        skill = _parse_hold_skill(template, slot, skill_unlock, strength)
        if skill:
            if switch_cond:
                skill["switch_cond"] = switch_cond
            skills.append(skill)
    return skills


def _parse_skill_block(
    block: str, slot: int, condition: str, switch_cond: str | None
) -> list[dict]:
    plain, groups = _tabber_split(block)
    if not groups:
        return _parse_skill_templates(block, slot, condition, switch_cond)

    skills = []
    for label, content in groups:
        if _ignore_variant_label(label):
            continue
        skills.extend(
            _parse_skill_templates(content, slot, condition, _switch_label(label) or switch_cond)
        )
    if plain.strip():
        skills.extend(_parse_skill_templates(plain, slot, condition, switch_cond))
    return skills


def _parse_skill_blocks(content: str, switch_cond: str | None = None) -> list[dict]:
    skills = []
    for slot, condition, block in _split_skill_blocks(content):
        skills.extend(_parse_skill_block(block, slot, condition, switch_cond))
    return skills


def _dedupe_skills(skills: list[dict]) -> list[dict]:
    deduped = {}
    for skill in skills:
        key = (skill["slot"], skill["name"], skill["strength"], skill.get("switch_cond") or "")
        deduped[key] = skill
    return list(deduped.values())


def parse_skill_forms(text: str) -> list[dict]:
    section = _find_section(text, "===持有技能===", ("===职阶技能===", "===追加技能==="))
    if not section:
        return []

    plain, tabbers = _extract_tabbers(section)
    if not tabbers:
        return [{"stages": {1, 2, 3, 4}, "skills": _parse_skill_blocks(section)}]

    plain_skills = _parse_skill_blocks(plain)
    global_skills: list[dict] = []
    ascension_groups = None

    for tabber in tabbers:
        groups = tabber["groups"]
        if not groups:
            continue
        active = [(label, content) for label, content in groups if not _ignore_variant_label(label)]
        if not active:
            continue
        single_variant = len(active) == 1
        section_level = any(_starts_with_skill_header(content) for _label, content in groups)

        if section_level and _has_ascension_labels(groups):
            if ascension_groups is None:
                ascension_groups = groups
            else:
                for label, content in active:
                    cond = None if single_variant else _switch_label(label)
                    global_skills.extend(_parse_skill_blocks(content, cond))
            continue

        if section_level:
            for label, content in active:
                cond = None if single_variant else _switch_label(label)
                global_skills.extend(_parse_skill_blocks(content, cond))
            continue

        header = _header_before(section, tabber["start"])
        for label, content in active:
            cond = None if single_variant else _switch_label(label)
            if header:
                slot, condition = header
                global_skills.extend(_parse_skill_templates(content, slot, condition, cond))
            else:
                global_skills.extend(_parse_skill_blocks(content, cond))

    if ascension_groups is not None:
        forms = []
        for stages, content in _assign_form_stages(ascension_groups, ""):
            skills = list(plain_skills) + list(global_skills) + _parse_skill_blocks(content)
            forms.append({"stages": stages, "skills": _dedupe_skills(skills)})
        return forms

    return [{"stages": {1, 2, 3, 4}, "skills": _dedupe_skills(plain_skills + global_skills)}]


def parse_class_skills(text: str) -> list[dict]:
    section = _find_section(text, "===职阶技能===", ("===追加技能===", "===灵衣开放===", "==技能"))
    if not section:
        return []
    plain, groups = _tabber_split(section)
    if groups:
        # Class skills are normally identical across battle forms; use the
        # first (normal) tab and ignore transformation/NPC variants.
        plain += groups[0][1]
    skills = []
    for template in _find_templates(plain, "职阶技能"):
        params = _positional_params(template)
        for index in range(0, len(params) - 3, 4):
            _icon, name, rank, effect = params[index : index + 4]
            if not name:
                continue
            skills.append({"name": name, "rank": rank, "effect": effect})
    return skills


def _parse_np_blocks(content: str, switch_cond: str | None = None) -> list[dict]:
    strengthened = "强化信息" in content
    strengthen_stage = _strengthen_stage(content) or 1
    seen_names = set()
    nps = []
    for template in _find_templates(content, "宝具"):
        params = _parse_template(template)
        name = params.get("中文名", "").strip()
        if not name:
            continue
        effects = _parse_info_effects(params.get("宝具信息", ""))
        if not effects:
            for letter in EFFECT_LETTERS:
                effect = params.get("效果" + letter)
                if not effect:
                    continue
                values = []
                for index in range(1, 6):
                    value = params.get(f"数值{letter}{index}")
                    if value is not None:
                        values.append(value.strip())
                if not values:
                    single = params.get("数值" + letter)
                    if single:
                        values = [single.strip()]
                effects.append({"text": effect, "values": values})
        is_strengthened = strengthened and name in seen_names
        seen_names.add(name)
        nps.append(
            {
                "name": name,
                "card": params.get("卡色", "").strip(),
                "rank": params.get("阶级", "").strip(),
                "type": params.get("种类", "").strip(),
                "strength": 1 if is_strengthened else 0,
                "unlock_stage": strengthen_stage if is_strengthened else 1,
                "switch_cond": switch_cond,
                "effects": effects,
            }
        )
    return nps


def _dedupe_nps(nps: list[dict]) -> list[dict]:
    deduped = {}
    for np in nps:
        key = (np["name"], np["strength"], np.get("switch_cond") or "")
        deduped[key] = np
    return list(deduped.values())


def parse_np_forms(text: str) -> list[dict]:
    section = _find_section(text, "==宝具==", ("==技能==",))
    if not section:
        return []
    plain, tabbers = _extract_tabbers(section)
    if not tabbers:
        return [{"stages": {1, 2, 3, 4}, "nobles": _parse_np_blocks(section)}]

    plain_nps = _parse_np_blocks(plain)
    global_nps: list[dict] = []
    ascension_groups = None

    for tabber in tabbers:
        groups = tabber["groups"]
        if not groups:
            continue
        active = [(label, content) for label, content in groups if not _ignore_variant_label(label)]
        if not active:
            continue
        single_variant = len(active) == 1

        if _has_ascension_labels(groups) and ascension_groups is None:
            ascension_groups = groups
            continue

        for label, content in active:
            cond = None if single_variant else _switch_label(label)
            global_nps.extend(_parse_np_blocks(content, cond))

    if ascension_groups is not None:
        forms = []
        for stages, content in _assign_form_stages(ascension_groups, ""):
            nps = list(plain_nps) + list(global_nps) + _parse_np_blocks(content)
            forms.append({"stages": stages, "nobles": _dedupe_nps(nps)})
        return forms

    return [{"stages": {1, 2, 3, 4}, "nobles": _dedupe_nps(plain_nps + global_nps)}]


def parse_servant_data(text: str) -> dict:
    return {
        "skill_forms": parse_skill_forms(text),
        "class_skills": parse_class_skills(text),
        "noble_forms": parse_np_forms(text),
    }


def parse_nps(text: str) -> list[dict]:
    """Return the {{宝具}} blocks in page order (base then strengthened)."""
    text = _strip_comments(text)
    records = []
    for template in _find_templates(text, "宝具"):
        params = _parse_template(template)
        name = params.get("中文名", "").strip()
        effects = _parse_info_effects(params.get("宝具信息", ""))
        if not effects:
            for letter in EFFECT_LETTERS:
                effect = params.get("效果" + letter)
                if not effect:
                    continue
                values = []
                for index in range(1, 6):
                    value = params.get(f"数值{letter}{index}")
                    if value is not None:
                        values.append(value.strip())
                if not values:
                    single = params.get("数值" + letter)
                    if single:
                        values = [single.strip()]
                effects.append({"text": effect, "values": values})
        records.append({"name": name, "effects": effects})
    return records


def parse_servant_list(text: str) -> dict[int, str]:
    rows = {}
    for block in re.split(r"\n\s*\n", text.strip()):
        fields = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key.strip()] = value.strip()
        if fields.get("id", "").isdigit() and fields.get("name_link"):
            rows[int(fields["id"])] = fields["name_link"]
    return rows


def fetch_servant_list(cache_dir: Path, refresh: bool = False) -> dict[int, str]:
    path = cache_dir / "servant_list.wiki"
    if refresh or not path.is_file():
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(_fetch(LIST_TITLE), encoding="utf-8")
    return parse_servant_list(path.read_text(encoding="utf-8"))


def fetch_pages(cache_dir: Path, titles: dict[int, str], refresh: bool = False) -> dict[int, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    missing = [key for key in titles if refresh or not (cache_dir / f"{key}.wiki").is_file()]

    def download(key: int) -> None:
        try:
            text = _fetch(titles[key])
        except Exception as exc:  # noqa: BLE001 - keep going with the rest
            print(f"  mooncell: {titles[key]}: {exc}")
            return
        (cache_dir / f"{key}.wiki").write_text(text, encoding="utf-8")

    if missing:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(download, key) for key in missing]
            for future in as_completed(futures):
                future.result()

    result = {}
    for key in titles:
        path = cache_dir / f"{key}.wiki"
        if path.is_file():
            result[key] = path.read_text(encoding="utf-8")
    return result


def build_index(cache_dir: Path, collection_nos: list[int], refresh: bool = False) -> dict[int, dict]:
    """Map collection number -> parsed skills / class skills / noble phantasms."""
    titles = fetch_servant_list(cache_dir, refresh=refresh)
    wanted = {no: titles[no] for no in collection_nos if no in titles}
    pages = fetch_pages(cache_dir, wanted, refresh=refresh)
    return {no: parse_servant_data(text) for no, text in pages.items()}
