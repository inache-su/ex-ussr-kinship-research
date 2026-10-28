"""Тесты build_tree.py на временном деле, созданном init_case.py.

Запуск: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


class BuildTree(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.case = Path(self.tmp.name) / "ivanova-maria-case"
        subprocess.run([sys.executable, str(SCRIPTS / "init_case.py"), "--case-dir", str(self.case),
                        "--research-question", "q"], check=True, capture_output=True)
        self.add("person-register.csv",
                 dict(person_id="P-0001", preferred_label="Иван Петров", living_status="deceased",
                      birth_estimate="1898", death_estimate="1974"),
                 dict(person_id="P-0002", preferred_label="Мария Иванова <script>", living_status="probably-living",
                      birth_estimate="1950"),
                 dict(person_id="P-0003", preferred_label="Олег Сидоров", birth_estimate="1948"),
                 dict(person_id="P-0004", preferred_label="Однофамилец", birth_estimate="1890", death_estimate="1940"),
                 dict(person_id="P-0005", preferred_label="Отвергнутый", birth_estimate="1900", death_estimate="1960"))
        self.add("relationship-register.csv",
                 dict(relationship_id="R-0001", person_a_id="P-0001", relationship_type="parent-of",
                      person_b_id="P-0002", status="single-source"),
                 dict(relationship_id="R-0002", person_a_id="P-0002", relationship_type="spouse-of",
                      person_b_id="P-0003", status="hypothesis"),
                 dict(relationship_id="R-0003", person_a_id="P-0005", relationship_type="parent-of",
                      person_b_id="P-0001", status="contradicted"))
        self.add("artifact-register.csv", dict(artifact_id="A-0001", source_title="Мария: семейное свидетельство",
                                              source_url_or_path="https://example.org/private-maria"))
        self.add("claims-register.csv", dict(claim_id="C-0001", subject_person_ids="P-0001",
                                            claim_text="Мария родилась в 1950 году", artifact_ids="A-0001",
                                            status="single-source"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def add(self, name: str, *rows: dict) -> None:
        path = self.case / name
        with path.open(encoding="utf-8", newline="") as handle:
            fields = next(csv.reader(handle))
        with path.open("a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fields).writerows(rows)

    def build(self, *extra: str) -> tuple[subprocess.CompletedProcess, str]:
        proc = subprocess.run([sys.executable, str(SCRIPTS / "build_tree.py"), "--case-dir", str(self.case), *extra],
                              capture_output=True, text=True)
        out = self.case / ("tree-shared.html" if "--shared" in extra else "tree.html")
        return proc, out.read_text(encoding="utf-8") if out.exists() else ""

    def test_tree_marks_hypotheses_and_separates_unlinked(self):
        proc, page = self.build()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.data(page)
        self.assertEqual([(e["id"], e["kind"], e["status"]) for e in data["relationships"]],
                         [("R-0001", "parent", "document"), ("R-0002", "spouse", "hypothesis"),
                          ("R-0003", "parent", "contradicted")])
        self.assertEqual([p["id"] for p in data["people"] if p["family"] == "unlinked"], ["P-0004", "P-0005"])
        self.assertEqual(data["unions"], [{"parents": ["P-0001"], "children": ["P-0002"], "rail": 268}])
        self.assertIn("C-0001 [single-source]", data["people"][0]["bio"])
        self.assertEqual(data["people"][0]["sources"][0]["title"], "Мария: семейное свидетельство")
        self.assertIn("Мария Иванова &lt;script&gt;", page)
        self.assertNotIn("Мария Иванова <script>", page)

    def data(self, page):
        return json.loads(re.search(r'id="tree-data" type="application/json">(.*?)</script>', page, re.S).group(1))

    def test_shared_version_hides_living(self):
        proc, page = self.build("--shared")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Мария", page)
        self.assertNotIn("1950", page)
        self.assertIn("М.И.s. (P-0002)", page)
        self.assertNotIn(self.case.name, page)
        self.assertNotIn("Олег Сидоров", page)  # без даты смерти и рождён меньше 100 лет назад
        self.assertIn("Иван Петров", page)
        self.assertNotIn("private-maria", page)
        self.assertEqual(self.data(page)["people"][1]["birth"], "")
        self.assertEqual(self.data(page)["people"][0]["sources"][0]["title"], "Источник из реестра дела")

    def test_parent_cycle_is_reported(self):
        out = self.case / "tree.html"
        out.write_text("previous map", encoding="utf-8")
        self.add("relationship-register.csv",
                 dict(relationship_id="R-0004", person_a_id="P-0002", relationship_type="parent-of",
                      person_b_id="P-0001", status="hypothesis"))
        proc, page = self.build()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("цикл", proc.stderr)
        self.assertEqual(page, "previous map")

    def test_duplicate_people_are_rejected(self):
        self.add("person-register.csv", dict(person_id="P-0001", preferred_label="Другой Иван"))
        proc, _ = self.build()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("повтор person_id", proc.stderr)

    def test_empty_case_and_custom_output(self):
        path = self.case / "person-register.csv"
        path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        out = self.case / "maps" / "empty.html"
        proc, _ = self.build("--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.data(out.read_text(encoding="utf-8"))["people"], [])

    def test_one_file_csp_and_input_escaping(self):
        self.add("person-register.csv", dict(person_id="P-0006", preferred_label='</script><img src=x onerror=alert(1)> __TREE_COPY__',
                                            birth_estimate="около 1880", living_status="deceased"))
        before = {p.name: p.read_bytes() for p in self.case.glob("*.csv")}
        proc, page = self.build()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.case.glob("*.csv")})
        self.assertEqual(self.data(page)["people"][-1]["birth"], "около 1880")
        self.assertIn("__TREE_COPY__", self.data(page)["people"][-1]["name"])
        self.assertNotIn("</script><img", page)
        self.assertNotRegex(page, r"<script[^>]+src=")
        self.assertNotIn("@import", page)
        self.assertIn("data:font/woff2;base64,", page)
        script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
        self.assertIn("script-src 'sha256-" + digest + "'", page)
        self.assertIn("connect-src 'none'", page)
        alias = self.case / "register-alias.csv"
        alias.symlink_to(self.case / "person-register.csv")
        proc, _ = self.build("--out", str(alias))
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(before["person-register.csv"], (self.case / "person-register.csv").read_bytes())

    def test_other_relationship_types_keep_separate_people(self):
        self.add("person-register.csv", dict(person_id="P-0006", preferred_label="Другой Иван"))
        self.add("relationship-register.csv",
                 dict(relationship_id="R-0004", person_a_id="P-0006", relationship_type="same-person",
                      person_b_id="P-0001", status="hypothesis"),
                 dict(relationship_id="R-0005", person_a_id="P-0005", relationship_type="godparent-of",
                      person_b_id="P-0002", status="single-source", supporting_artifact_ids="A-0001"))
        proc, page = self.build()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = self.data(page)
        self.assertEqual(len(data["people"]), 6)
        self.assertEqual(data["relationships"][-2]["kind"], "same-person")
        edge = data["relationships"][-1]
        self.assertEqual((edge["kind"], edge["evidenceStatus"], edge["sources"][0]["id"]),
                         ("godparent", "single-source", "A-0001"))


if __name__ == "__main__":
    unittest.main()
