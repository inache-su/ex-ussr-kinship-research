#!/usr/bin/env python3
"""Build an offline interactive family atlas from the case registers."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from audit_evidence import split_ids
from research_common import atomic_bytes

PARENT = "parent-of"
SAME_ROW = {"spouse-of", "sibling-of"}
# Старые дела до словаря relationship_type (SKILL.md, шаг 2).
LEGACY = {"mother": PARENT, "father": PARENT, "possible-father": PARENT,
          "spouse": "spouse-of", "possible-siblings": "sibling-of"}
EVIDENCED = {"single-source", "corroborated", "strongly-corroborated"}
LIVING = {"living", "probably-living"}
esc = html.escape
ASSETS = Path(__file__).resolve().parent.parent / "assets" / "family-tree"
KINDS = {PARENT: "parent", "spouse-of": "spouse", "sibling-of": "sibling",
         "step-parent-of": "step", "godparent-of": "godparent",
         "same-person": "same-person", "relative-of": "unplaced"}


def read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def birth_year(value: str) -> int | None:
    match = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value)
    return int(match.group(1)) if match else None


def maybe_living(person: dict[str, str]) -> bool:
    """В версии для обмена живым считается человек без даты смерти, родившийся меньше 100 лет назад или без года рождения."""
    status = person.get("living_status", "").casefold()
    if status in LIVING:
        return True
    if status == "deceased" or person.get("death_estimate"):
        return False
    year = birth_year(person.get("birth_estimate", ""))
    return year is None or year > date.today().year - 100


def name_of(person: dict[str, str], shared: bool) -> str:
    name = person.get("preferred_label") or person.get("names_as_written") or person["person_id"]
    if shared and maybe_living(person):
        return "".join(word[0] + "." for word in re.findall(r"[^\W\d_]+", name)[:3]) + f" ({person['person_id']})"
    return name


def generations(ids: list[str], edges: list[tuple[str, str, str]]) -> dict[str, int]:
    gen = dict.fromkeys(ids, 0)
    for _ in range(len(ids) + 1):
        changed = False
        for a, kind, b in edges:
            if kind == PARENT and gen[b] < gen[a] + 1:
                gen[b], changed = gen[a] + 1, True
            elif kind in SAME_ROW and gen[a] != gen[b]:
                gen[a] = gen[b] = max(gen[a], gen[b])
                changed = True
        if not changed:
            low = min(gen.values(), default=0)
            return {pid: value - low for pid, value in gen.items()}
    raise ValueError("цикл в связях parent-of или противоречие поколений; проверьте relationship-register.csv")


def components(ids: list[str], edges: list[tuple[str, str, str]]) -> list[list[str]]:
    parent = {pid: pid for pid in ids}

    def root(pid: str) -> str:
        while parent[pid] != pid:
            parent[pid] = parent[parent[pid]]
            pid = parent[pid]
        return pid

    for a, _, b in edges:
        parent[root(a)] = root(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for pid in ids:
        groups[root(pid)].append(pid)
    return sorted(groups.values(), key=lambda group: (-len(group), group[0]))


def order_rows(group: list[str], gen: dict[str, int], edges: list[tuple[str, str, str]]) -> list[list[str]]:
    rows: dict[int, list[str]] = defaultdict(list)
    for pid in group:
        rows[gen[pid]].append(pid)
    position: dict[str, float] = {}
    result = []
    for level in sorted(rows):
        keys = {}
        for pid in rows[level]:
            parents = [position[a] for a, kind, b in edges if b == pid and kind == PARENT and a in position]
            keys[pid] = sum(parents) / len(parents) if parents else float("inf")
        for a, kind, b in edges:  # супруг без родителей в дереве встаёт рядом с партнёром
            if kind == "spouse-of" and a in keys and b in keys:
                if keys[a] == float("inf"):
                    keys[a] = keys[b] + 0.1
                elif keys[b] == float("inf"):
                    keys[b] = keys[a] + 0.1
        row = sorted(rows[level], key=lambda pid: (keys[pid], pid))
        position.update({pid: index for index, pid in enumerate(row)})
        result.append(row)
    return result


def dates(person: dict[str, str]) -> str:
    """Показывать только годы; полные оценки дат с пояснениями остаются в реестре."""
    born, died = birth_year(person.get("birth_estimate", "")), birth_year(person.get("death_estimate", ""))
    if died:
        return f"{born or '?'} — {died}"
    return str(born or "")


def atlas(case_dir: Path, shared: bool) -> tuple[dict, dict[str, int]]:
    rows = [p for p in read(case_dir / "person-register.csv") if p.get("person_id")
            and p.get("candidate_status", "").casefold() != "superseded"]
    persons = {p["person_id"]: p for p in rows}
    if len(persons) != len(rows):
        raise ValueError("повтор person_id в person-register.csv")
    artifacts = {a["artifact_id"]: a for a in read(case_dir / "artifact-register.csv") if a.get("artifact_id")}
    claims = {c["claim_id"]: c for c in read(case_dir / "claims-register.csv") if c.get("claim_id")}

    def sources(ids):
        result = []
        for aid in dict.fromkeys(ids):
            artifact = artifacts.get(aid, {})
            title = "Источник из реестра дела" if shared else " · ".join(filter(None, [
                artifact.get("source_title"), artifact.get("archival_reference"), artifact.get("record_date")]))
            result.append({"id": aid, "title": title or aid,
                           "locator": "" if shared else artifact.get("source_url_or_path", "")})
        return result

    relationships, edges, seen = [], [], set()
    for number, row in enumerate(read(case_dir / "relationship-register.csv"), start=2):
        a, b = row.get("person_a_id", ""), row.get("person_b_id", "")
        if a not in persons or b not in persons:
            continue  # Связи исключённых кандидатов, как и прежде, не переносятся.
        rid = row.get("relationship_id", "")
        if not rid or rid in seen or a == b:
            raise ValueError(f"неверный или повторный relationship_id либо связь с собой, строка {number}")
        seen.add(rid)
        kind = LEGACY.get(row.get("relationship_type", ""), row.get("relationship_type", ""))
        if kind not in KINDS:
            raise ValueError(f"неизвестный relationship_type: {kind} ({rid})")
        status = row.get("status", "")
        artifact_ids = split_ids(row.get("supporting_artifact_ids", "")) + split_ids(row.get("contradicting_artifact_ids", ""))
        for cid in split_ids(row.get("claim_ids", "")):
            artifact_ids.extend(split_ids(claims.get(cid, {}).get("artifact_ids", "")))
        relationships.append({
            "id": rid, "from": a, "to": b, "kind": KINDS[kind],
            "status": "contradicted" if status == "contradicted" else "document" if status in EVIDENCED else "hypothesis",
            "evidenceStatus": status, "relationshipType": kind,
            "note": "" if shared else row.get("rationale", ""),
            "sources": sources(artifact_ids), "claimIds": split_ids(row.get("claim_ids", "")),
        })
        if status != "contradicted":
            edges.append((a, kind, b))

    linked = sorted({pid for a, _, b in edges for pid in (a, b)})
    loose = sorted(set(persons) - set(linked))
    gen = generations(linked, edges)
    groups = components(linked, edges)
    people = {}
    for pid, person in persons.items():
        hidden = shared and maybe_living(person)
        related_claims = [c for c in claims.values() if pid in split_ids(c.get("subject_person_ids", ""))]
        artifact_ids = split_ids(person.get("source_artifact_ids", ""))
        for claim in related_claims:
            artifact_ids.extend(split_ids(claim.get("artifact_ids", "")))
        for edge in relationships:
            if pid in (edge["from"], edge["to"]):
                artifact_ids.extend(s["id"] for s in edge["sources"])
        paragraphs = [f"{label}: {person[field]}" for field, label in [
            ("places", "Места"), ("historical_jurisdictions", "Исторические юрисдикции"),
            ("occupation_or_status", "Занятие или сословие"),
            ("confession_or_community_as_recorded", "Конфессия или община в источнике"),
            ("relatives_as_reported", "Родственники по сообщению источника"),
            ("candidate_status", "Статус кандидата"), ("merge_or_split_rationale", "Основания сопоставления"),
        ] if person.get(field)]
        if person.get("notes"):
            paragraphs.append(person["notes"])
        paragraphs.extend(f"{c['claim_id']} [{c.get('status') or 'без статуса'}]: {c.get('claim_text', '')}"
                          for c in related_claims)
        aliases = list(dict.fromkeys(split_ids(person.get("names_as_written", ""))
                                    + split_ids(person.get("normalized_name_variants", ""))))
        people[pid] = {
            "id": pid, "name": name_of(person, shared), "surname": "", "patronymic": "",
            "birth": "" if hidden else person.get("birth_estimate", ""),
            "death": "" if hidden else person.get("death_estimate", ""),
            "birth_year": None if hidden else birth_year(person.get("birth_estimate", "")),
            "death_year": None if hidden else birth_year(person.get("death_estimate", "")),
            "life": "" if hidden else dates(person), "role": pid, "record": pid,
            "aliases": [] if shared else aliases,
            # Свободный текст даже об умершем может называть живых родственников.
            "bio": "Подробности скрыты в версии для обмена." if shared else "\n\n".join(paragraphs) or "Сведения в реестре пока не заполнены.",
            "sources": sources(artifact_ids),
        }

    # The viewer expands these rows to make room for connectors.
    card_w, card_h, gap, step = 224, 128, 48, 240
    sections, branches = [], {}
    x, bottom = 56, 0
    for number, group in enumerate(groups, start=1):
        key, label = f"c{number}", f"Связанная группа {number}"
        branches[key] = label
        sections.append({"x": x, "y": 80, "text": label})
        rows = order_rows(group, gen, edges)
        width = max(map(len, rows)) * (card_w + gap) - gap
        for row in rows:
            start = x + (width - len(row) * (card_w + gap) + gap) / 2
            for index, pid in enumerate(row):
                people[pid].update(x=start + index * (card_w + gap), y=100 + gen[pid] * step, family=key)
                bottom = max(bottom, people[pid]["y"] + card_h)
        x += width + 112
    if loose:
        y = bottom + 160 if groups else 100
        branches["unlinked"] = "Записи без связей"
        sections.append({"x": 56, "y": y - 40, "text": branches["unlinked"]})
        for index, pid in enumerate(loose):
            people[pid].update(x=56 + index % 4 * (card_w + gap), y=y + index // 4 * step, family="unlinked")
        bottom = max(p["y"] + card_h for p in people.values())
    width = max(x, 112 + min(4, len(loose)) * (card_w + gap) - gap, 640)
    unions = []
    for edge in relationships:
        a, b = people[edge["from"]], people[edge["to"]]
        edge["rail"] = max(a["y"], b["y"]) + card_h + 36
        edge["labelX"] = (a["x"] + b["x"] + card_w) / 2
        if edge["kind"] == "parent" and edge["status"] != "contradicted":
            unions.append({"parents": [a["id"]], "children": [b["id"]], "rail": a["y"] + card_h + 40})
    counts = {"persons": len(people), "linked": len(linked), "unlinked": len(loose), "groups": len(groups)}
    return {"title": "Семейное древо", "updated": date.today().isoformat(),
            "width": width, "height": max(bottom + 120, 360), "cardWidth": card_w, "cardHeight": card_h,
            "people": list(people.values()), "relationships": relationships, "unions": unions,
            "sections": sections, "branches": branches}, counts


def embedded(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def build(case_dir: Path, shared: bool) -> tuple[str, dict[str, int]]:
    data, counts = atlas(case_dir, shared)
    copy = json.loads((ASSETS / "ui.json").read_text(encoding="utf-8"))
    copy["families"] = "Версия для обмена" if shared else f"Дело {case_dir.name} · рабочая версия"
    fallback = [f'<main class="no-js-fallback"><h1>{esc(copy["title"])}</h1><p>{esc(copy["noJs"])}</p>']
    for person in data["people"]:
        fallback.append(f'<details id="{esc(person["id"])}"><summary>{esc(person["name"])}</summary>'
                        + f'<p>{esc(person["life"])}</p>'
                        + "".join(f"<p>{esc(p)}</p>" for p in person["bio"].split("\n\n")) + "</details>")
    fallback.append("</main>")
    font_css = (ASSETS / "fonts" / "fonts.css").read_text(encoding="utf-8")
    for filename in dict.fromkeys(re.findall(r"url\(([^)]+)\)", font_css)):
        font = base64.b64encode((ASSETS / "fonts" / filename).read_bytes()).decode("ascii")
        font_css = font_css.replace(f"url({filename})", f"url(data:font/woff2;base64,{font})")
    css = (ASSETS / "style.css").read_text(encoding="utf-8").replace('@import url("fonts/fonts.css");', font_css)
    script = (ASSETS / "app.js").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    page = (ASSETS / "index.html").read_text(encoding="utf-8")
    # Заменяем только маркеры шаблона; данные не должны становиться шаблоном.
    replacements = {"__TREE_DATA__": embedded(data), "__TREE_COPY__": embedded(copy),
                    "__NO_SCRIPT__": "".join(fallback), "__TREE_STYLE__": css,
                    "__TREE_SCRIPT__": script, "__SCRIPT_HASH__": digest}
    page = re.sub(r"__(?:TREE_DATA|TREE_COPY|NO_SCRIPT|TREE_STYLE|TREE_SCRIPT|SCRIPT_HASH)__",
                  lambda match: replacements[match.group()], page)
    return page, counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Строит интерактивную HTML-карту семьи из реестров дела.")
    parser.add_argument("--case-dir", required=True, help="Директория дела")
    parser.add_argument("--out", help="Файл страницы; по умолчанию tree.html (tree-shared.html с --shared) в деле")
    parser.add_argument("--shared", action="store_true", help="Версия для обмена: живые люди — инициалы, без дат; свободные тексты скрыты")
    args = parser.parse_args()
    case_dir = Path(args.case_dir).expanduser().resolve()
    if not (case_dir / "person-register.csv").is_file():
        print(f"Ошибка: не найден person-register.csv в {case_dir}", file=sys.stderr)
        return 2
    out = Path(args.out).expanduser().resolve() if args.out else case_dir / ("tree-shared.html" if args.shared else "tree.html")
    if out in {(case_dir / name).resolve() for name in ("person-register.csv", "relationship-register.csv", "artifact-register.csv", "claims-register.csv")}:
        print("Ошибка: HTML не должен перезаписывать реестры дела", file=sys.stderr)
        return 2
    try:
        page, counts = build(case_dir, args.shared)
        atomic_bytes(out, page.encode("utf-8"))
    except (ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"{out}: людей {counts['persons']}, в дереве {counts['linked']}, без связей {counts['unlinked']}, групп {counts['groups']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
