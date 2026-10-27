#!/usr/bin/env python3
"""Audit cross-references and corroboration claims without assigning truth."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Iterable

REQUIRED_FILES = {
    "artifact-register.csv": {
        "artifact_id",
        "independence_group",
        "directness",
        "originality",
        "related_claim_ids",
        "status",
    },
    "claims-register.csv": {
        "claim_id",
        "artifact_ids",
        "supporting_independence_groups",
        "contradicting_artifact_ids",
        "status",
        "rationale",
    },
    "relationship-register.csv": {
        "relationship_id",
        "person_a_id",
        "person_b_id",
        "claim_ids",
        "supporting_artifact_ids",
        "contradicting_artifact_ids",
        "independence_groups",
        "status",
        "rationale",
    },
    "person-register.csv": {"person_id"},
}

CORROBORATED = {"corroborated", "strongly-corroborated"}
VALID_CLAIM_STATUSES = {
    "",
    "hypothesis",
    "single-source",
    "corroborated",
    "strongly-corroborated",
    "contradicted",
    "unresolved",
}
FINAL_STATUSES = CORROBORATED | {"contradicted"}
EVIDENCED = CORROBORATED | {"single-source"}
RESULT_STATUSES = {"found", "partial", "not-found", "blocked", "skipped"}
LIVING_STATUSES = {"", "living", "probably-living", "deceased", "unknown"}
RELATIONSHIP_TYPES = {
    "parent-of", "step-parent-of", "spouse-of", "sibling-of", "godparent-of", "same-person", "relative-of",
}
CONFIDENCE = {"", "low", "moderate", "high"}
TOOL_LABELS = {
    "web", "web search", "web-search", "web.search", "web.run", "веб-поиск", "search", "поиск", "browser", "браузер",
}


def birth_year(value: str) -> int | None:
    match = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value)
    return int(match.group(1)) if match else None


def mentioned(record_id: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(record_id)}(?!\w)", text) is not None


def examples(items: list[str], limit: int = 5) -> str:
    """Сводный список для предупреждения: первые ID и число остальных."""
    shown = ", ".join(items[:limit])
    return shown + (f" и ещё {len(items) - limit}" if len(items) > limit else "")


def split_ids(value: str) -> list[str]:
    if not value:
        return []
    normalized = value.replace(",", ";")
    return [part.strip() for part in normalized.split(";") if part.strip()]


def read_csv(path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                return [], [f"{path.name}: отсутствует строка заголовка"]
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                errors.append(f"{path.name}: отсутствуют колонки: {', '.join(missing)}")
            rows = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
            return rows, errors
    except OSError as exc:
        return [], [f"{path.name}: ошибка чтения: {exc}"]


def duplicate_ids(rows: Iterable[dict[str, str]], field: str) -> list[str]:
    ids = [row.get(field, "") for row in rows if row.get(field, "")]
    return sorted(key for key, count in Counter(ids).items() if count > 1)


def artifact_groups(artifact_ids: Iterable[str], artifact_by_id: dict[str, dict[str, str]]) -> set[str]:
    return {
        artifact_by_id[artifact_id]["independence_group"].strip().casefold()
        for artifact_id in artifact_ids
        if artifact_id in artifact_by_id
        and artifact_by_id[artifact_id].get("independence_group", "").strip()
    }


def has_direct_record(artifact_ids: Iterable[str], artifact_by_id: dict[str, dict[str, str]]) -> bool:
    """Одна и та же запись должна быть прямой и иметь описанное происхождение.

    Непустое описание и локатор — проверка заполнения, не доказательство
    подлинности документа или истинности заключения.
    """
    for artifact_id in artifact_ids:
        row = artifact_by_id.get(artifact_id, {})
        provenance = row.get("provenance_level", "").strip().casefold()
        if (
            row.get("directness", "").casefold() == "direct"
            and row.get("originality", "").casefold()
            in {"original", "image-of-original", "official-extract"}
            and provenance not in {"", "unknown", "неизвестно", "не установлено"}
            and (row.get("source_url_or_path", "").strip() or row.get("archival_reference", "").strip())
        ):
            return True
    return False


def id_prefix(value: str) -> str:
    """Префикс ID без номера: 'A-0001' -> 'A-'."""
    return value.rstrip("0123456789")


REPORT_MARKERS = ("[неразборчиво]", "[предположительно")
HEADING_RE = re.compile(r"^#{2,6}\s")


def audit_report(
    text: str,
    known_ids: dict[str, set[str]],
    statuses: dict[str, str],
) -> tuple[list[str], dict[str, int]]:
    """Сверить ID и статусы итогового отчёта с реестрами.

    known_ids: префикс -> ID этого префикса из реестров. Стандартные префиксы
    проверяются и при пустых реестрах; плейсхолдеры (`A-....`) не содержат номера.
    statuses: ID утверждения или связи -> статус в реестре.
    """
    errors: list[str] = []
    for prefix, ids in sorted(known_ids.items()):
        pattern = re.compile(rf"(?<![\w-]){re.escape(prefix)}\d+(?!\w)")
        for cited in sorted(set(pattern.findall(text)) - ids):
            errors.append(f"final-report.md: ссылка на {cited}, которого нет в реестрах")

    valid = VALID_CLAIM_STATUSES - {""}
    section_id = ""
    section_checked = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if HEADING_RE.match(stripped):
            words = re.findall(r"[\w-]+", stripped)
            section_id = next((word for word in words if word in statuses), "")
            section_checked = False
            continue
        if stripped.startswith("|"):
            # Строка таблицы с ID в первой ячейке и статусом в одной из ячеек.
            cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
            row_id, row_statuses = cells[0], [cell for cell in cells[1:] if cell in valid]
            if row_id in statuses and row_statuses and statuses[row_id] not in row_statuses:
                errors.append(
                    f"final-report.md:{number}: {row_id} — в отчёте {row_statuses[0]}, в реестре {statuses[row_id] or 'пусто'}"
                )
            continue
        # Первое поле вида **Статус:** value в секции связи/утверждения.
        match = re.match(r"^\*\*[^*]+:\*\*\s*`?([\w-]+)`?", stripped)
        if section_id and not section_checked and match and match.group(1) in valid:
            section_checked = True
            if match.group(1) != statuses[section_id]:
                errors.append(
                    f"final-report.md:{number}: {section_id} — в отчёте {match.group(1)}, в реестре {statuses[section_id] or 'пусто'}"
                )

    markers = {marker.strip("[]"): text.count(marker) for marker in REPORT_MARKERS}
    return errors, markers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Проверяет целостность реестров и минимальные условия кроссподтверждения."
    )
    parser.add_argument("--case-dir", required=True, help="Директория дела")
    parser.add_argument("--json", action="store_true", help="Вывести JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Возвращать ненулевой код также при предупреждениях",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_dir = Path(args.case_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not case_dir.is_dir():
        print(f"Ошибка: директория дела не найдена: {case_dir}", file=sys.stderr)
        return 2

    data: dict[str, list[dict[str, str]]] = {}
    for filename, required in REQUIRED_FILES.items():
        path = case_dir / filename
        if not path.is_file():
            errors.append(f"Отсутствует обязательный файл: {filename}")
            data[filename] = []
            continue
        rows, file_errors = read_csv(path, required)
        errors.extend(file_errors)
        data[filename] = rows

    artifacts = data["artifact-register.csv"]
    claims = data["claims-register.csv"]
    relationships = data["relationship-register.csv"]
    persons = data["person-register.csv"]

    for rows, field, label in [
        (artifacts, "artifact_id", "артефакта"),
        (claims, "claim_id", "утверждения"),
        (relationships, "relationship_id", "связи"),
        (persons, "person_id", "лица"),
    ]:
        duplicates = duplicate_ids(rows, field)
        if duplicates:
            errors.append(f"Дублирующиеся ID {label}: {', '.join(duplicates)}")
        for index, row in enumerate(rows, start=2):
            if not row.get(field, ""):
                warnings.append(f"{field}: пустой ID в строке {index}")

    artifact_by_id = {row["artifact_id"]: row for row in artifacts if row.get("artifact_id")}
    claim_by_id = {row["claim_id"]: row for row in claims if row.get("claim_id")}
    person_ids = {row["person_id"] for row in persons if row.get("person_id")}

    odd_living = [
        row.get("person_id") or "?"
        for row in persons
        if row.get("living_status", "").casefold() not in LIVING_STATUSES
    ]
    if odd_living:
        warnings.append(
            f"person-register.csv: living_status вне списка {', '.join(sorted(LIVING_STATUSES - {''}))}: "
            + examples(odd_living)
        )
    oldest_living = date.today().year - 100
    unmarked = [
        row.get("person_id") or "?"
        for row in persons
        if row.get("living_status", "").casefold() in {"", "unknown"}
        and not row.get("death_estimate", "")
        and (birth_year(row.get("birth_estimate", "")) or 0) > oldest_living
    ]
    if unmarked:
        warnings.append(
            "person-register.csv: родились меньше 100 лет назад без сведений о смерти, "
            "но living_status не probably-living: " + examples(unmarked)
        )
    odd_types = sorted({row.get("relationship_type", "") or "пусто" for row in relationships} - RELATIONSHIP_TYPES)
    if odd_types:
        warnings.append(
            f"relationship-register.csv: relationship_type вне списка {', '.join(sorted(RELATIONSHIP_TYPES))}: "
            + examples(odd_types)
        )
    odd_confidence = [
        row.get("claim_id") or row.get("relationship_id") or "?"
        for row in claims + relationships
        if row.get("confidence", "").casefold() not in CONFIDENCE
    ]
    if odd_confidence:
        warnings.append("confidence вне списка low, moderate, high: " + examples(odd_confidence))

    for artifact_id, row in artifact_by_id.items():
        if not row.get("independence_group", "").strip():
            warnings.append(f"{artifact_id}: не указан independence_group")
        for person_id in split_ids(row.get("person_ids", "")):
            if person_id not in person_ids:
                errors.append(f"{artifact_id}: неизвестный person_id {person_id}")
        for claim_id in split_ids(row.get("related_claim_ids", "")):
            if claim_id not in claim_by_id:
                errors.append(f"{artifact_id}: неизвестный related claim_id {claim_id}")

    for claim_id, row in claim_by_id.items():
        status = row.get("status", "")
        if status not in VALID_CLAIM_STATUSES:
            warnings.append(f"{claim_id}: неизвестный статус {status!r}")
        for person_id in split_ids(row.get("subject_person_ids", "")):
            if person_id not in person_ids:
                errors.append(f"{claim_id}: неизвестный subject_person_id {person_id}")
        referenced = split_ids(row.get("artifact_ids", ""))
        contradictory = split_ids(row.get("contradicting_artifact_ids", ""))
        for artifact_id in referenced + contradictory:
            if artifact_id not in artifact_by_id:
                errors.append(f"{claim_id}: неизвестный artifact_id {artifact_id}")
        if referenced and all(
            artifact_by_id.get(artifact_id, {}).get("source_type", "").casefold() == "research-note"
            for artifact_id in referenced
        ):
            warnings.append(
                f"{claim_id}: опирается только на заметки исследования (research-note); сошлитесь на исходные документы"
            )

        groups = artifact_groups(referenced, artifact_by_id)
        for group in sorted(set(split_ids(row.get("supporting_independence_groups", "")))):
            if group.casefold() not in groups:
                errors.append(
                    f"{claim_id}: independence_group {group} заявлен, но ни один из artifact_ids к нему не относится"
                )

        if status in CORROBORATED and len(groups) < 2:
            warnings.append(
                f"{claim_id}: статус {status}, но найдено независимых групп: {len(groups)}"
            )
        if status in CORROBORATED and not row.get("rationale"):
            warnings.append(f"{claim_id}: для {status} отсутствует rationale")
        if status in CORROBORATED and contradictory:
            warnings.append(
                f"{claim_id}: статус {status}, но указаны противоречащие артефакты; "
                "проверьте и объясните, разрешён ли существенный конфликт"
            )
        if status == "single-source" and len(groups) > 1:
            warnings.append(
                f"{claim_id}: несколько независимых групп, но статус всё ещё single-source; проверьте конфликт/полноту"
            )
        if status == "strongly-corroborated" and not has_direct_record(referenced, artifact_by_id):
            warnings.append(
                f"{claim_id}: strongly-corroborated без единой прямой записи "
                "с указанным происхождением и локатором оригинала, образа или официальной выписки"
            )

    for row in relationships:
        relation_id = row.get("relationship_id", "<без ID>")
        status = row.get("status", "")
        if status not in VALID_CLAIM_STATUSES:
            warnings.append(f"{relation_id}: неизвестный статус {status!r}")
        for person_field in ("person_a_id", "person_b_id"):
            person_id = row.get(person_field, "")
            if person_id and person_id not in person_ids:
                errors.append(f"{relation_id}: неизвестный {person_field} {person_id}")
        for claim_id in split_ids(row.get("claim_ids", "")):
            if claim_id not in claim_by_id:
                errors.append(f"{relation_id}: неизвестный claim_id {claim_id}")
        artifact_refs = split_ids(row.get("supporting_artifact_ids", "")) + split_ids(
            row.get("contradicting_artifact_ids", "")
        )
        for artifact_id in artifact_refs:
            if artifact_id not in artifact_by_id:
                errors.append(f"{relation_id}: неизвестный artifact_id {artifact_id}")
        # Группа засчитывается, только если за ней стоит артефакт: прямой или через claim_ids.
        backing_ids = split_ids(row.get("supporting_artifact_ids", ""))
        contradictory = set(split_ids(row.get("contradicting_artifact_ids", "")))
        for claim_id in split_ids(row.get("claim_ids", "")):
            if claim_id in claim_by_id:
                backing_ids += split_ids(claim_by_id[claim_id].get("artifact_ids", ""))
                contradictory.update(split_ids(claim_by_id[claim_id].get("contradicting_artifact_ids", "")))
        groups = artifact_groups(backing_ids, artifact_by_id)
        for group in sorted(set(split_ids(row.get("independence_groups", "")))):
            if group.casefold() not in groups:
                errors.append(
                    f"{relation_id}: independence_group {group} заявлен, но ни один из артефактов связи к нему не относится"
                )
        if status in CORROBORATED:
            if len(groups) < 2:
                warnings.append(
                    f"{relation_id}: статус {row.get('status')}, но указано независимых групп: {len(groups)}"
                )
            if not row.get("rationale"):
                warnings.append(f"{relation_id}: отсутствует rationale")
            if contradictory:
                warnings.append(
                    f"{relation_id}: статус {status}, но указаны противоречащие артефакты; "
                    "проверьте и объясните, разрешён ли существенный конфликт"
                )
        if status == "strongly-corroborated" and not has_direct_record(backing_ids, artifact_by_id):
            warnings.append(
                f"{relation_id}: strongly-corroborated без единой прямой записи "
                "с указанным происхождением и локатором оригинала, образа или официальной выписки"
            )

    # Гипотеза допустима на одно звено от субъекта дела или человека с подтверждённой связью.
    intake = case_dir / "case-intake.yaml"
    anchors = set(re.findall(r'person_id:\s*"?(P-\d+)', intake.read_text(encoding="utf-8"))) if intake.is_file() else set()
    for row in relationships:
        if row.get("status", "") in EVIDENCED:
            anchors.update((row.get("person_a_id", ""), row.get("person_b_id", "")))
    hypotheses = [row for row in relationships if row.get("status") == "hypothesis" and row.get("relationship_id")]
    far = [
        row["relationship_id"]
        for row in hypotheses
        if row.get("person_a_id") not in anchors and row.get("person_b_id") not in anchors
    ]
    if far:
        warnings.append(
            "relationship-register.csv: гипотезы дальше одного звена от субъекта дела или подтверждённой связи: "
            + examples(far)
            + "; держите их наводками в research-state.md"
        )

    # Итоговый отчёт: ссылки и статусы должны совпадать с реестрами.
    markers: dict[str, int] = {}
    report = case_dir / "final-report.md"
    if report.is_file():
        known_ids: dict[str, set[str]] = {
            prefix: set() for prefix in ("A-", "C-", "R-", "P-")
        }
        for rows, field in [
            (artifacts, "artifact_id"),
            (claims, "claim_id"),
            (relationships, "relationship_id"),
            (persons, "person_id"),
        ]:
            for row in rows:
                if row.get(field, "") and id_prefix(row[field]) != row[field]:
                    known_ids.setdefault(id_prefix(row[field]), set()).add(row[field])
        statuses = {claim_id: row.get("status", "") for claim_id, row in claim_by_id.items()}
        statuses.update(
            (row["relationship_id"], row.get("status", ""))
            for row in relationships
            if row.get("relationship_id")
        )
        report_text = report.read_text(encoding="utf-8-sig")
        report_errors, markers = audit_report(report_text, known_ids, statuses)
        errors.extend(report_errors)
        unreported = [
            row["relationship_id"]
            for row in relationships
            if row.get("relationship_id")
            and row.get("status", "") in FINAL_STATUSES
            and not mentioned(row["relationship_id"], report_text)
        ]
        if unreported:
            warnings.append(
                "final-report.md: не упомянуты связи с итоговым статусом: "
                + examples(unreported)
                + "; обновите отчёт"
            )
        unreported_hypotheses = [
            row["relationship_id"]
            for row in hypotheses
            if (row.get("person_a_id") in anchors or row.get("person_b_id") in anchors)
            and not mentioned(row["relationship_id"], report_text)
        ]
        if unreported_hypotheses:
            warnings.append(
                "final-report.md: в разделе «Гипотезы» не упомянуты: " + examples(unreported_hypotheses)
            )

    # Журнал поиска: фиксированные статусы и повторы одного запроса в одном источнике.
    log_path = case_dir / "search-log.csv"
    if log_path.is_file():
        log_rows, log_errors = read_csv(
            log_path, {"search_id", "query", "source_or_domain", "result_status"}
        )
        errors.extend(log_errors)
        odd_status = [
            row.get("search_id") or "?"
            for row in log_rows
            if row.get("result_status", "").casefold() not in RESULT_STATUSES
        ]
        if odd_status:
            warnings.append(
                f"search-log.csv: result_status вне списка {', '.join(sorted(RESULT_STATUSES))} "
                f"в строках: {len(odd_status)} ({examples(odd_status)}); подробности пишите в blocker и next_step"
            )
        tools = [
            row.get("search_id") or "?"
            for row in log_rows
            if row.get("source_or_domain", "").strip().casefold() in TOOL_LABELS
        ]
        if tools:
            warnings.append(
                f"search-log.csv: в source_or_domain название инструмента вместо сайта или архива: "
                f"{len(tools)} ({examples(tools)})"
            )
        seen: dict[tuple[str, str], str] = {}
        repeats: list[str] = []
        for row in log_rows:
            query = " ".join(row.get("query", "").casefold().split())
            if not query:
                continue
            key = (query, row.get("source_or_domain", "").strip().casefold())
            search_id = row.get("search_id") or "?"
            if key in seen:
                repeats.append(f"{seen[key]}→{search_id}")
            else:
                seen[key] = search_id
        if repeats:
            warnings.append(
                f"search-log.csv: повторы того же запроса в том же источнике: {len(repeats)} "
                f"({examples(repeats)}); без нового основания не повторяйте, основание пишите в next_step"
            )

    # Сводка готовности: что ещё не снято. Не ошибки — для решения, выдавать ли отчёт.
    summary = {
        "claims_by_status": dict(Counter(row.get("status", "") or "пусто" for row in claims)),
        "relationships_by_status": dict(
            Counter(row.get("status", "") or "пусто" for row in relationships)
        ),
        "report_markers": markers,
    }

    result = {
        "case_dir": str(case_dir),
        "counts": {
            "persons": len(persons),
            "artifacts": len(artifacts),
            "claims": len(claims),
            "relationships": len(relationships),
        },
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Проверено дело: {case_dir}")
        print(
            "Записей: "
            f"лица={len(persons)}, артефакты={len(artifacts)}, "
            f"утверждения={len(claims)}, связи={len(relationships)}"
        )
        open_statuses = ("hypothesis", "single-source", "unresolved", "contradicted", "пусто")
        print("\nСВОДКА:")
        for label, key in [("утверждения", "claims_by_status"), ("связи", "relationships_by_status")]:
            counts = summary[key]
            line = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
            pending = sum(counts.get(status, 0) for status in open_statuses)
            print(f"- {label}: {line or 'нет'}; без кроссподтверждения: {pending}")
        if markers:
            print("- в отчёте: " + ", ".join(f"[{name}]={count}" for name, count in markers.items()))
        if errors:
            print("\nОШИБКИ:")
            for item in errors:
                print(f"- {item}")
        if warnings:
            print("\nПРЕДУПРЕЖДЕНИЯ:")
            for item in warnings:
                print(f"- {item}")
        if not errors and not warnings:
            print("Ошибок и предупреждений не найдено.")

    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
