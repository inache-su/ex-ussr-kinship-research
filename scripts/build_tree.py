#!/usr/bin/env python3
"""Build a static HTML family tree from the case registers."""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

PARENT = "parent-of"
SAME_ROW = {"spouse-of", "sibling-of"}
# Старые дела до словаря relationship_type (SKILL.md, шаг 2).
LEGACY = {"mother": PARENT, "father": PARENT, "possible-father": PARENT,
          "spouse": "spouse-of", "possible-siblings": "sibling-of"}
EVIDENCED = {"single-source", "corroborated", "strongly-corroborated"}
LIVING = {"living", "probably-living"}
LABELS = {
    PARENT: ("ребёнок", "родитель"),
    "step-parent-of": ("пасынок или падчерица", "отчим или мачеха"),
    "godparent-of": ("крестник или крестница", "восприемник или восприемница"),
    "spouse-of": ("супруг или супруга", "супруг или супруга"),
    "sibling-of": ("брат или сестра", "брат или сестра"),
    "same-person": ("возможно, тот же человек", "возможно, тот же человек"),
    "relative-of": ("родственник", "родственник"),
}
esc = html.escape


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


def card(pid, person, relations, shared, names) -> str:
    meta = pid if shared and maybe_living(person) else " · ".join(filter(None, [pid, dates(person)]))
    items = "".join(
        f"<li>{esc(role)}: {esc(names[other])} <span class=\"status\">{esc(status or 'без статуса')}</span></li>"
        for role, other, status in relations
    )
    details = f"<details><summary>Связи ({len(relations)})</summary><ul>{items}</ul></details>" if relations else ""
    return (f'<article class="person" id="{esc(pid)}"><h3>{esc(names[pid])}</h3>'
            f'<p class="meta">{esc(meta)}</p>{details}</article>')


def build(case_dir: Path, shared: bool) -> tuple[str, dict[str, int]]:
    persons = {p["person_id"]: p for p in read(case_dir / "person-register.csv")
               if p.get("person_id") and p.get("candidate_status", "").casefold() != "superseded"}
    names = {pid: name_of(p, shared) for pid, p in persons.items()}
    drawn, relations = [], defaultdict(list)
    for row in read(case_dir / "relationship-register.csv"):
        a, b = row.get("person_a_id", ""), row.get("person_b_id", "")
        if a not in persons or b not in persons:
            continue
        kind = LEGACY.get(row.get("relationship_type", ""), row.get("relationship_type", ""))
        status = row.get("status", "")
        to_b, to_a = LABELS.get(kind, (kind, kind))
        relations[a].append((to_b, b, status))
        relations[b].append((to_a, a, status))
        if status != "contradicted":  # опровергнутые связи видны только в карточках
            drawn.append((a, kind, b, status in EVIDENCED))
    edges = [(a, kind, b) for a, kind, b, _ in drawn]
    linked = sorted({pid for a, _, b in edges for pid in (a, b)})
    gen = generations(linked, edges)
    sections, edge_data = [], {}
    for number, group in enumerate(components(linked, edges), start=1):
        members = set(group)
        rows = "".join(
            '<div class="row">' + "".join(card(pid, persons[pid], relations[pid], shared, names) for pid in row) + "</div>"
            for row in order_rows(group, gen, edges)
        )
        edge_data[f"c{number}"] = [[a, b, "parent" if kind == PARENT else "row", not proved]
                                   for a, kind, b, proved in drawn if a in members]
        sections.append(f'<section class="component" id="c{number}"><svg aria-hidden="true"></svg>{rows}</section>')
    loose = [pid for pid in sorted(persons) if pid not in set(linked)]
    loose_html = "".join(card(pid, persons[pid], relations[pid], shared, names) for pid in loose)
    counts = {"persons": len(persons), "linked": len(linked), "unlinked": len(loose), "groups": len(sections)}
    page = TEMPLATE.format(
        # имя папки дела часто содержит имя живого человека
        title="" if shared else f" · {esc(case_dir.name)}",
        case="" if shared else f"Дело {esc(case_dir.name)} · ",
        mode="версия для обмена: живые люди — инициалы, без дат" if shared else "рабочая версия",
        today=date.today().isoformat(),
        summary=f"Людей: {counts['persons']}, в дереве: {counts['linked']}, без связей: {counts['unlinked']}.",
        groups="".join(sections) or "<p>Связей в реестре пока нет.</p>",
        loose=f'<div class="loose">{loose_html}</div>' if loose else "<p>Нет.</p>",
        edges=json.dumps(edge_data, ensure_ascii=False).replace("</", "<\\/"),
    )
    return page, counts


TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Семейное дерево{title}</title>
<style>
:root{{--bg:#edf2f5;--paper:#fff;--ink:#233b4a;--muted:#536b79;--line:#cfdae1;--proved:#29685c;--hyp:#8b611c}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1400px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:18px;margin:32px 0 12px}}h3{{font-size:15px;margin:0}}
.lead,.meta{{color:var(--muted);margin:0}}.meta{{font-size:13px}}
.legend{{display:flex;flex-wrap:wrap;gap:16px;margin:12px 0 0;color:var(--muted);font-size:13px}}
.legend i{{display:inline-block;width:32px;border-top:2px solid var(--proved);vertical-align:middle;margin-right:6px}}
.legend i.hyp{{border-top:2px dashed var(--hyp)}}
.component{{position:relative;overflow-x:auto;background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}}
.component svg{{position:absolute;inset:0;pointer-events:none}}
.row{{position:relative;display:flex;gap:16px;justify-content:center;align-items:flex-start;margin:0 0 40px;min-width:max-content}}.row:last-child{{margin-bottom:0}}
.person{{position:relative;z-index:1;width:200px;background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:10px 12px}}
.person:target{{outline:2px solid var(--proved)}}
details{{margin-top:6px;font-size:13px}}summary{{cursor:pointer;color:var(--muted)}}
ul{{margin:6px 0 0;padding-left:18px}}.status{{color:var(--muted)}}
line{{stroke:var(--proved);stroke-width:1.5}}line.hyp{{stroke:var(--hyp);stroke-dasharray:6 4}}
.loose{{display:flex;flex-wrap:wrap;gap:12px}}
@media print{{body{{background:#fff}}.component{{break-inside:avoid}}}}
</style>
</head>
<body>
<main>
<h1>Семейное дерево</h1>
<p class="lead">{case}{mode} · собрано {today}. {summary}</p>
<p class="legend"><span><i></i>связь подтверждена записью (single-source и выше)</span><span><i class="hyp"></i>гипотеза или нерешённая связь</span></p>
<h2>Связанные группы</h2>
{groups}
<h2>Записи без связей</h2>
{loose}
</main>
<script type="application/json" id="edges">{edges}</script>
<script>
const EDGES = JSON.parse(document.getElementById('edges').textContent);
function draw() {{
  for (const [id, list] of Object.entries(EDGES)) {{
    const box = document.getElementById(id), svg = box.querySelector('svg'), at = box.getBoundingClientRect();
    svg.setAttribute('width', box.scrollWidth); svg.setAttribute('height', box.scrollHeight); svg.replaceChildren();
    for (const [a, b, kind, hyp] of list) {{
      const A = document.getElementById(a).getBoundingClientRect(), B = document.getElementById(b).getBoundingClientRect();
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      const dx = box.scrollLeft - at.left, dy = box.scrollTop - at.top;
      line.setAttribute('x1', A.left + A.width / 2 + dx); line.setAttribute('x2', B.left + B.width / 2 + dx);
      line.setAttribute('y1', (kind === 'parent' ? A.bottom : A.top + A.height / 2) + dy);
      line.setAttribute('y2', (kind === 'parent' ? B.top : B.top + B.height / 2) + dy);
      if (hyp) line.setAttribute('class', 'hyp');
      svg.appendChild(line);
    }}
  }}
}}
addEventListener('load', draw); addEventListener('resize', draw);
document.querySelectorAll('details').forEach(d => d.addEventListener('toggle', draw));
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Строит HTML-страницу семейного дерева из реестров дела.")
    parser.add_argument("--case-dir", required=True, help="Директория дела")
    parser.add_argument("--out", help="Файл страницы; по умолчанию tree.html (tree-shared.html с --shared) в деле")
    parser.add_argument("--shared", action="store_true", help="Версия для обмена: живые люди — инициалы, без дат")
    args = parser.parse_args()
    case_dir = Path(args.case_dir).expanduser().resolve()
    if not (case_dir / "person-register.csv").is_file():
        print(f"Ошибка: не найден person-register.csv в {case_dir}", file=sys.stderr)
        return 2
    try:
        page, counts = build(case_dir, args.shared)
    except ValueError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out).expanduser() if args.out else case_dir / ("tree-shared.html" if args.shared else "tree.html")
    out.write_text(page, encoding="utf-8")
    print(f"{out}: людей {counts['persons']}, в дереве {counts['linked']}, без связей {counts['unlinked']}, групп {counts['groups']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
