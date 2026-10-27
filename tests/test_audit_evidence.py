"""Тесты audit_evidence.py на временных делах, созданных init_case.py.

Запуск: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.audit_evidence import artifact_groups, has_direct_record

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

ARTIFACT = "{id},,title,url,,,,,,,P-0001,,,,direct,image-of-original,{group},clear,,,{claims},,"
CLAIM = "{id},text,P-0001,birth,{artifacts},{groups},,{status},moderate,rationale,"
PERSON = "{id},,,,,,,,,,,,,,,"
RELATION = "{id},P-0001,parent-of,P-0002,biological,{claims},{artifacts},,{groups},{status},moderate,rationale"
LOG = "{id},,,,{query},,{source},,{status},,,,"


class AuditCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.case = Path(self.tmp.name) / "case"
        subprocess.run(
            [sys.executable, str(SCRIPTS / "init_case.py"), "--case-dir", str(self.case),
             "--research-question", "q"],
            check=True, capture_output=True,
        )
        self.append("person-register.csv", PERSON.format(id="P-0001"), PERSON.format(id="P-0002"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def append(self, name: str, *lines: str) -> None:
        with (self.case / name).open("a", encoding="utf-8") as handle:
            handle.write("".join(line + "\n" for line in lines))

    def audit(self) -> dict:
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "audit_evidence.py"), "--case-dir", str(self.case), "--json"],
            capture_output=True, text=True,
        )
        return json.loads(proc.stdout)

    def update_row(self, name: str, record_id: str, **changes: str) -> None:
        path = self.case / name
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        for row in rows:
            if row[fields[0]] == record_id:
                row.update(changes)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def two_artifacts(self, second_group: str = "G2") -> None:
        self.append(
            "artifact-register.csv",
            ARTIFACT.format(id="A-0001", group="G1", claims="C-0001"),
            ARTIFACT.format(id="A-0002", group=second_group, claims="C-0001"),
        )

    def test_fresh_case_is_clean(self):
        # Плейсхолдеры шаблона отчёта (A-...., R-0001 при пустых реестрах) не дают ошибок.
        result = self.audit()
        self.assertEqual(result["errors"], [])

    def test_declared_group_without_artifact_is_error(self):
        self.append("artifact-register.csv", ARTIFACT.format(id="A-0001", group="G1", claims="C-0001"))
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="G1;G2", status="corroborated"))
        result = self.audit()
        self.assertTrue(any("C-0001: independence_group G2" in e for e in result["errors"]))
        self.assertTrue(any("C-0001: статус corroborated" in w for w in result["warnings"]))

    def test_backed_groups_corroborate(self):
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="G1;G2", status="corroborated"))
        result = self.audit()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_copies_share_group(self):
        self.two_artifacts(second_group="G1")
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="G1", status="corroborated"))
        result = self.audit()
        self.assertTrue(any("найдено независимых групп: 1" in w for w in result["warnings"]))

    def test_group_case_and_whitespace_do_not_create_independence(self):
        self.assertEqual(
            artifact_groups(["A-0001", "A-0002"], {
                "A-0001": {"independence_group": " G1 "},
                "A-0002": {"independence_group": "   "},
            }),
            {"g1"},
        )
        self.two_artifacts(second_group="  g1  ")
        self.append("artifact-register.csv", ARTIFACT.format(id="A-0003", group="   ", claims="C-0001"))
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002;A-0003", groups="G1;g1", status="corroborated"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="g1",
                                    status="corroborated"))
        result = self.audit()
        self.assertEqual(result["errors"], [])
        self.assertIn("A-0003: не указан independence_group", result["warnings"])
        self.assertTrue(any("C-0001: статус corroborated, но найдено независимых групп: 1" in w
                            for w in result["warnings"]))
        self.assertTrue(any("R-0001: статус corroborated, но указано независимых групп: 1" in w
                            for w in result["warnings"]))

    def test_strong_corroboration_needs_one_direct_original_record(self):
        self.two_artifacts()
        self.update_row("artifact-register.csv", "A-0001", originality="derivative", provenance_level="documented")
        self.update_row("artifact-register.csv", "A-0002", directness="indirect", provenance_level="documented")
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="", status="strongly-corroborated"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="",
                                    status="strongly-corroborated"))
        warnings = self.audit()["warnings"]
        for record_id in ("C-0001", "R-0001"):
            self.assertTrue(any(w.startswith(record_id + ": strongly-corroborated без единой прямой записи")
                                for w in warnings))

    def test_strong_corroboration_checks_provenance_and_locator(self):
        self.assertFalse(has_direct_record(["A-0001"], {
            "A-0001": {"directness": "direct", "originality": "original", "provenance_level": "documented",
                       "source_url_or_path": "   ", "archival_reference": "   "},
        }))
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="", status="strongly-corroborated"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="",
                                    status="strongly-corroborated"))
        self.update_row("artifact-register.csv", "A-0002", directness="indirect")
        for provenance, locator, qualifies in [
            ("", "url", False),
            ("unknown", "url", False),
            ("documented", "", False),
            ("documented", "   ", False),
            ("documented", "url", True),
        ]:
            with self.subTest(provenance=provenance, locator=locator):
                self.update_row("artifact-register.csv", "A-0001", provenance_level=provenance,
                                source_url_or_path=locator)
                result = self.audit()
                self.assertEqual(result["errors"], [])
                for record_id in ("C-0001", "R-0001"):
                    missing_record = any(w.startswith(record_id + ": strongly-corroborated без единой прямой записи")
                                         for w in result["warnings"])
                    self.assertEqual(missing_record, not qualifies)

    def test_corroborated_conflicts_warn_for_claims_and_relationships(self):
        self.two_artifacts()
        self.append("artifact-register.csv", ARTIFACT.format(id="A-0003", group="G3", claims=""))
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="", status="corroborated"))
        self.update_row("claims-register.csv", "C-0001", contradicting_artifact_ids="A-0003")
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="", status="corroborated"),
                    RELATION.format(id="R-0002", claims="", artifacts="A-0001;A-0002", groups="", status="corroborated"))
        self.update_row("relationship-register.csv", "R-0002", contradicting_artifact_ids="A-0003")
        result = self.audit()
        self.assertEqual(result["errors"], [])
        for record_id in ("C-0001", "R-0001", "R-0002"):
            self.assertTrue(any(w.startswith(record_id + ": статус corroborated, но указаны противоречащие артефакты")
                                for w in result["warnings"]))

    def test_person_references_and_relationship_status_are_checked(self):
        self.two_artifacts()
        self.update_row("artifact-register.csv", "A-0001", person_ids="P-9999")
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="", status="single-source"))
        self.update_row("claims-register.csv", "C-0001", subject_person_ids="P-9998")
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="", status="invented"))
        self.update_row("relationship-register.csv", "R-0001", person_b_id="P-9997")
        result = self.audit()
        for expected in ("A-0001: неизвестный person_id P-9999",
                         "C-0001: неизвестный subject_person_id P-9998",
                         "R-0001: неизвестный person_b_id P-9997"):
            self.assertIn(expected, result["errors"])
        self.assertIn("R-0001: неизвестный статус 'invented'", result["warnings"])

    def test_relationship_groups_come_from_claims(self):
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001;A-0002", groups="", status="corroborated"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="G1;G2",
                                    status="corroborated"),
                    RELATION.format(id="R-0002", claims="", artifacts="A-0001", groups="G1;G9",
                                    status="corroborated"))
        result = self.audit()
        self.assertFalse(any(e.startswith("R-0001") for e in result["errors"]))
        self.assertTrue(any("R-0002: independence_group G9" in e for e in result["errors"]))

    def test_report_unknown_ids_are_errors(self):
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="", status="single-source"))
        self.append("final-report.md", "", "Вывод [A-0001; A-0099], см. C-0042.")
        errors = self.audit()["errors"]
        self.assertTrue(any("A-0099" in e for e in errors))
        self.assertTrue(any("C-0042" in e for e in errors))
        self.assertFalse(any("A-0001" in e for e in errors))

    def test_report_unknown_ids_with_empty_registers(self):
        self.append("final-report.md", "", "Вывод [A-0099], см. C-0042 и R-0003.")
        errors = self.audit()["errors"]
        for cited in ("A-0099", "C-0042", "R-0003"):
            self.assertTrue(any(cited in error for error in errors), cited)

    def test_report_status_must_match_register(self):
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="", status="single-source"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="C-0001", artifacts="", groups="",
                                    status="single-source"))
        self.append("final-report.md", "", "### R-0001: P-0001 — отец — P-0002", "",
                    "**Статус:** `corroborated`", "",
                    "| C-0001 | текст | corroborated | A-0001 |  |  |")
        errors = self.audit()["errors"]
        self.assertTrue(any("R-0001 — в отчёте corroborated, в реестре single-source" in e for e in errors))
        self.assertTrue(any("C-0001 — в отчёте corroborated, в реестре single-source" in e for e in errors))

    def test_init_creates_research_state(self):
        self.assertTrue((self.case / "research-state.md").is_file())

    def test_search_log_vocabulary_and_repeats(self):
        self.append("search-log.csv",
                    LOG.format(id="S-0001", query="Иванов  Пётр", source="ya.ru", status="found"),
                    LOG.format(id="S-0002", query="Петров", source="ya.ru", status="нашлось 3"),
                    LOG.format(id="S-0003", query="иванов пётр", source="ya.ru", status="not-found"),
                    LOG.format(id="S-0004", query="Иванов Пётр", source="obd-memorial.ru", status="found"))
        warnings = self.audit()["warnings"]
        self.assertTrue(any("result_status вне списка" in w and "S-0002" in w and "S-0001" not in w
                            for w in warnings))
        self.assertTrue(any("в том же источнике: 1 " in w and "S-0001→S-0003" in w for w in warnings))

    def test_claim_backed_only_by_research_notes_warns(self):
        self.two_artifacts()
        self.update_row("artifact-register.csv", "A-0001", source_type="research-note")
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="", status="single-source"),
                    CLAIM.format(id="C-0002", artifacts="A-0001;A-0002", groups="", status="single-source"))
        warnings = self.audit()["warnings"]
        self.assertTrue(any(w.startswith("C-0001: опирается только на заметки") for w in warnings))
        self.assertFalse(any(w.startswith("C-0002: опирается только на заметки") for w in warnings))

    def test_final_relationship_missing_from_report_warns(self):
        self.two_artifacts()
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="", artifacts="A-0001;A-0002", groups="",
                                    status="corroborated"),
                    RELATION.format(id="R-0002", claims="", artifacts="A-0001", groups="",
                                    status="hypothesis"))
        self.assertTrue(any("не упомянуты связи с итоговым статусом: R-0001" in w
                            for w in self.audit()["warnings"]))
        self.append("final-report.md", "", "### R-0001: P-0001 — отец — P-0002", "", "**Статус:** `corroborated`")
        self.assertFalse(any("не упомянуты связи" in w for w in self.audit()["warnings"]))

    def test_living_status_vocabulary(self):
        self.update_row("person-register.csv", "P-0001", living_status="probably-living")
        self.update_row("person-register.csv", "P-0002", living_status="жив?")
        warnings = self.audit()["warnings"]
        self.assertTrue(any("living_status вне списка" in w and "P-0002" in w and "P-0001" not in w
                            for w in warnings))

    def test_vocabularies_and_probably_living_default(self):
        self.two_artifacts()
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="", artifacts="A-0001", groups="", status="hypothesis"))
        self.update_row("relationship-register.csv", "R-0001", relationship_type="possible-father", confidence="medium")
        self.update_row("person-register.csv", "P-0002", birth_estimate="около 1990 года")
        self.append("search-log.csv", LOG.format(id="S-0001", query="Петров", source="Веб-поиск", status="found"))
        warnings = self.audit()["warnings"]
        for expected in ("relationship_type вне списка", "possible-father", "confidence вне списка", "R-0001",
                         "но living_status не probably-living: P-0002", "название инструмента вместо сайта"):
            self.assertTrue(any(expected in w for w in warnings), expected)

    def test_hypothesis_chain_and_report_section(self):
        self.append("person-register.csv", PERSON.format(id="P-0003"), PERSON.format(id="P-0004"))
        self.append("relationship-register.csv",
                    RELATION.format(id="R-0001", claims="", artifacts="", groups="", status="hypothesis"),
                    RELATION.format(id="R-0002", claims="", artifacts="", groups="", status="hypothesis"))
        self.update_row("relationship-register.csv", "R-0001", person_b_id="P-0003")
        self.update_row("relationship-register.csv", "R-0002", person_a_id="P-0003", person_b_id="P-0004")
        warnings = self.audit()["warnings"]
        chain = [w for w in warnings if "гипотезы дальше одного звена" in w]
        self.assertTrue(chain and "R-0002" in chain[0] and "R-0001" not in chain[0])
        self.assertTrue(any("в разделе «Гипотезы» не упомянуты: R-0001" in w for w in warnings))
        self.append("final-report.md", "", "| R-0001 | P-0001 — P-0003 | — | фамилия и место | акт о рождении |")
        self.assertFalse(any("в разделе «Гипотезы»" in w for w in self.audit()["warnings"]))

    def test_summary_counts_open_items(self):
        self.two_artifacts()
        self.append("claims-register.csv",
                    CLAIM.format(id="C-0001", artifacts="A-0001", groups="", status="hypothesis"))
        self.append("final-report.md", "Фамилия [неразборчиво], отец [предположительно: Пётр].")
        summary = self.audit()["summary"]
        self.assertEqual(summary["claims_by_status"], {"hypothesis": 1})
        self.assertEqual(summary["report_markers"], {"неразборчиво": 1, "предположительно": 1})


if __name__ == "__main__":
    unittest.main()
