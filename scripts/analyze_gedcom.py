#!/usr/bin/env python3
"""Find research leads in a GEDCOM tree: weddings in fasts, early first children,
reused child names, patronymic mismatches and death clusters.

Checks adapted from genealogy-analyzer by Konstantin Popov (MIT License,
https://github.com/tamvodopad/claude-code-skill-genealogy-analyzer); rewritten
with exact Julian dates and a fuller list of church wedding restrictions.
Findings are leads for checking against the records, not conclusions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

if __package__:
    from .check_gedcom import parse
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # `python -I` omits the script folder.
    from check_gedcom import parse

MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
DATE = re.compile(r"(?:(?:@#D(?P<esc>[A-Z ]+)@|(?P<cal>JULIAN|GREGORIAN)) )?"
                  r"(?:(?P<day>[0-9]{1,2}) )?(?:(?P<mon>[A-Z]{3}) )?(?P<year>[0-9]{3,4})")
FIRST_CHILD_DAYS = 260   # Earlier births after a wedding are worth a check.
INFANT_YEARS = 5
CLUSTER_DAYS, CLUSTER_SIZE = 90, 3


def jdn(year: int, month: int, day: int, julian: bool) -> int:
    a = (14 - month) // 12
    y, m = year + 4800 - a, month + 12 * a - 3
    base = day + (153 * m + 2) // 5 + 365 * y + y // 4
    return base - 32083 if julian else base - y // 100 + y // 400 - 32045


def valid_day(year: int, month: int, day: int, julian: bool) -> bool:
    leap = year % 4 == 0 if julian else (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    return 1 <= day <= (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


def julian_easter(year: int) -> tuple[int, int]:
    """Orthodox Easter as a Julian (month, day), Meeus's algorithm."""
    d = (19 * (year % 19) + 15) % 30
    e = (2 * (year % 4) + 4 * (year % 7) - d + 34) % 7
    return (d + e + 114) // 31, (d + e + 114) % 31 + 1


def read_date(value: str | None, unmarked_julian: bool) -> dict | None:
    """Return {'year', 'jdn' (exact dates only), 'julian'} or None for unsupported values."""
    match = DATE.fullmatch((value or "").strip())
    if not match or (match["day"] and not match["mon"]) or (match["mon"] and match["mon"] not in MONTHS):
        return None
    calendar = match["esc"] or match["cal"]
    if calendar not in (None, "JULIAN", "GREGORIAN"):
        return None
    year = int(match["year"])
    julian = calendar == "JULIAN" or (calendar is None and unmarked_julian and year < 1918)
    result = {"year": year, "jdn": None, "julian": julian}
    if match["day"]:
        month, day = MONTHS[match["mon"]], int(match["day"])
        if not valid_day(year, month, day, julian):
            return None
        result["jdn"] = jdn(year, month, day, julian)
    return result


def forbidden_periods(year: int) -> list[tuple[int, int, str]]:
    """Julian-calendar periods without weddings in the Russian Orthodox Church."""
    def j(month: int, day: int) -> int:
        return jdn(year, month, day, True)
    easter = j(*julian_easter(year))
    periods = [
        (j(1, 1), j(1, 6), "Святки"),
        (easter - 55, easter - 1, "Масленица (сырная седмица) и Великий пост"),
        (easter, easter + 6, "Светлая седмица"),
        (easter + 57, j(6, 28), "Петров пост"),
        (j(8, 1), j(8, 14), "Успенский пост"),
        (j(8, 29), j(8, 29), "Усекновение главы Иоанна Предтечи (постный день)"),
        (j(9, 14), j(9, 14), "Воздвижение (постный день)"),
        (j(11, 15), j(12, 24), "Рождественский пост"),
        (j(12, 25), j(12, 31), "Святки"),
    ]
    return [period for period in periods if period[0] <= period[1]]


def name_parts(person) -> tuple[str, str, str]:
    """Return (given name, patronymic, label) from NAME «Иван Петрович /Иванов/»."""
    name = person.first("NAME")
    raw = (name.value or "") if name else ""
    givn = name.first("GIVN") if name else None
    given = (re.sub(r"/[^/]*/?", " ", raw).strip() or (givn.value if givn else "") or "").split()
    label = " ".join(raw.replace("/", " ").split()) or person.xref
    return (given[0] if given else ""), (given[1] if len(given) > 1 else ""), f"{label} ({person.xref})"


def norm(text: str) -> str:
    return text.casefold().replace("ё", "е").replace("й", "и").replace("ь", "")


def patronymic_fits(father: str, patronymic: str) -> bool:
    """Prefix test covering Иван/Иванович, Василий/Васильевич, Илья/Ильич, Павел/Павлович, Лев/Львович."""
    name, pat = norm(father), norm(patronymic)
    stem = name[:-1] if name[-1:] in "аяи" else name
    stems = {stem, re.sub(r"е(?=[^аеиоуыэюя]$)", "", stem), stem[:-1] if len(stem) > 3 else stem}
    return any(pat.startswith(s) for s in stems if s)


def event(person, tag: str, unmarked_julian: bool) -> dict | None:
    node = person.first(tag)
    return read_date(node.first("DATE").value, unmarked_julian) if node and node.first("DATE") else None


def analyze(text: str, before: int = 1918, unmarked_julian: bool = True) -> dict:
    errors: list[str] = []
    records = parse(text, errors, [])
    people = {r.xref: r for r in records if r.tag == "INDI" and r.xref}
    families = [r for r in records if r.tag == "FAM"]
    birth = {x: event(p, "BIRT", unmarked_julian) or event(p, "CHR", unmarked_julian) for x, p in people.items()}
    death = {x: event(p, "DEAT", unmarked_julian) or event(p, "BURI", unmarked_julian) for x, p in people.items()}
    label = {x: name_parts(p)[2] for x, p in people.items()}
    findings: dict[str, list[dict]] = defaultdict(list)

    def early(date: dict | None) -> bool:
        return bool(date) and date["year"] < before

    for family in families:
        children = [c for c in family.values("CHIL") if c in people]
        father = family.first("HUSB").value if family.first("HUSB") else None
        marr_node = family.first("MARR")
        marr = read_date(marr_node.first("DATE").value, unmarked_julian) if marr_node and marr_node.first("DATE") else None
        spouses = ", ".join(label[x] for x in family.values("HUSB") + family.values("WIFE") if x in label)

        if early(marr) and marr["jdn"] is not None:
            for start, end, period in forbidden_periods(marr["year"]):
                if start <= marr["jdn"] <= end:
                    findings["wedding_in_fast"].append({
                        "family": family.xref, "people": spouses, "date": marr_node.first("DATE").value,
                        "detail": f"венчание пришлось на период «{period}»: проверьте дату, календарь и чтение записи"})
            dated = sorted((birth[c]["jdn"], c) for c in children if birth[c] and birth[c]["jdn"] is not None)
            if dated and dated[0][0] - marr["jdn"] < FIRST_CHILD_DAYS:
                days, child = dated[0][0] - marr["jdn"], dated[0][1]
                when = "до венчания" if days < 0 else f"через {days} дн. после венчания"
                findings["early_first_child"].append({
                    "family": family.xref, "people": f"{spouses}; ребёнок {label[child]}",
                    "detail": f"первый датированный ребёнок родился {when}: возможны другой брак, "
                              "ошибка даты, перепутанная запись или рождение до брака"})

        named = defaultdict(list)
        for child in children:
            given, _, _ = name_parts(people[child])
            sex = people[child].first("SEX").value if people[child].first("SEX") else ""
            if given and early(birth[child]):
                named[(norm(given), sex)].append(child)
        for same in named.values():
            same.sort(key=lambda c: birth[c]["jdn"] or jdn(birth[c]["year"], 7, 1, False))
            for older, younger in zip(same, same[1:]):
                b_old, d_old, b_new = birth[older], death[older], birth[younger]
                if d_old and (d_old["year"] - b_old["year"] <= INFANT_YEARS) and (
                        (d_old["jdn"] and b_new["jdn"] and d_old["jdn"] <= b_new["jdn"]) or d_old["year"] < b_new["year"]):
                    detail = "имя умершего в детстве ребёнка дано следующему: это два разных человека"
                    kind = "replacement_name"
                else:
                    detail = ("одноимённые дети без даты смерти старшего до рождения младшего: "
                              "проверьте, не дубль ли это одного человека или второе имя")
                    kind = "same_name_siblings"
                findings[kind].append({"family": family.xref, "people": f"{label[older]}; {label[younger]}",
                                       "detail": detail})

        if father in people:
            father_name = name_parts(people[father])[0]
            for child in children:
                _, patronymic, child_label = name_parts(people[child])
                if father_name and patronymic and early(birth[child]) and not patronymic_fits(father_name, patronymic):
                    findings["patronymic_mismatch"].append({
                        "family": family.xref, "people": f"{child_label}; отец {label[father]}",
                        "detail": f"отчество «{patronymic}» не образовано от имени «{father_name}»: "
                                  "проверьте церковную и бытовую форму имени, отчима и связь в семье"})

    by_place = defaultdict(list)
    for xref, person in people.items():
        date = death[xref]
        if early(date) and date["jdn"] is not None:
            node = person.first("DEAT") or person.first("BURI")
            place = (node.first("PLAC").value or "").strip() if node.first("PLAC") else ""
            by_place[place.casefold() or "(место не указано)"].append((date["jdn"], xref, place))
    for key, deaths in by_place.items():
        deaths.sort()
        start = 0
        while start < len(deaths):
            end = start
            while end + 1 < len(deaths) and deaths[end + 1][0] - deaths[start][0] <= CLUSTER_DAYS:
                end += 1
            if end - start + 1 >= CLUSTER_SIZE:
                group = deaths[start:end + 1]
                findings["death_cluster"].append({
                    "place": group[0][2] or key, "people": "; ".join(label[x] for _, x, _ in group),
                    "detail": f"{len(group)} смертей за {group[-1][0] - group[0][0]} дн.: ищите эпидемию, "
                              "войну или голод в метрике и местной истории"})
                start = end + 1
            else:
                start += 1

    return {"before": before, "unmarked_calendar": "julian" if unmarked_julian else "gregorian",
            "counts": {"INDI": len(people), "FAM": len(families)}, "errors": errors,
            "findings": {kind: findings[kind] for kind in sorted(findings)}}


TITLES = {
    "wedding_in_fast": "Венчание в пост или в период без венчаний",
    "early_first_child": f"Первый ребёнок раньше {FIRST_CHILD_DAYS} дней после венчания",
    "replacement_name": "Имя умершего ребёнка дано следующему",
    "same_name_siblings": "Одноимённые братья или сёстры без объяснения",
    "patronymic_mismatch": "Отчество не сходится с именем отца",
    "death_cluster": f"Не меньше {CLUSTER_SIZE} смертей в одном месте за {CLUSTER_DAYS} дней",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ищет в GEDCOM наводки для проверки по документам; не делает выводов.")
    parser.add_argument("path", help="Путь к файлу .ged в UTF-8")
    parser.add_argument("--before", type=int, default=1918,
                        help="Учитывать события до этого года (по умолчанию 1918: церковные правила и приватность)")
    parser.add_argument("--unmarked", choices=("julian", "gregorian"), default="julian",
                        help="Календарь дат до 1918 года без пометки календаря (по умолчанию julian, как в метриках)")
    parser.add_argument("--json", action="store_true", help="Вывести JSON")
    args = parser.parse_args()
    path = Path(args.path).expanduser()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"Ошибка: не удалось прочитать {path} как UTF-8 ({exc}); проверьте файл через check_gedcom.py",
              file=sys.stderr)
        return 2
    result = analyze(text, args.before, args.unmarked == "julian")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(f"Файл: {path}; INDI {result['counts']['INDI']}, FAM {result['counts']['FAM']}; "
          f"события до {args.before} года; даты без пометки календаря считаются: {result['unmarked_calendar']}")
    for error in result["errors"]:
        print(f"Не разобрано: {error}")
    for kind, items in result["findings"].items():
        print(f"\n{TITLES[kind]}: {len(items)}")
        for item in items:
            where = item.get("family") or item.get("place")
            print(f"- {where}: {item['people']}. {item['detail']}" + (f" ({item['date']})" if "date" in item else ""))
    if not result["findings"]:
        print("Наводок не найдено.")
    return 0


if __name__ == "__main__":
    if __package__:
        from .research_common import configure_utf8_stdio
    else:
        from research_common import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
