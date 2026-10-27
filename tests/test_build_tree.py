"""Тесты build_tree.py на временном деле, созданном init_case.py.

Запуск: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import csv
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
        edges = json.loads(re.search(r'id="edges">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(edges, {"c1": [["P-0001", "P-0002", "parent", False], ["P-0002", "P-0003", "row", True]]})
        loose = page.split("Записи без связей")[1]
        self.assertIn('id="P-0004"', loose)
        self.assertIn('id="P-0005"', loose)  # только опровергнутая связь — в дерево не попадает
        self.assertIn("Мария Иванова &lt;script&gt;", page)
        self.assertNotIn("Мария Иванова <script>", page)

    def test_shared_version_hides_living(self):
        proc, page = self.build("--shared")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Мария", page)
        self.assertNotIn("1950", page)
        self.assertIn("М.И.s. (P-0002)", page)
        self.assertNotIn(self.case.name, page)
        self.assertNotIn("Олег Сидоров", page)  # без даты смерти и рождён меньше 100 лет назад
        self.assertIn("Иван Петров", page)

    def test_parent_cycle_is_reported(self):
        self.add("relationship-register.csv",
                 dict(relationship_id="R-0004", person_a_id="P-0002", relationship_type="parent-of",
                      person_b_id="P-0001", status="hypothesis"))
        proc, _ = self.build()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("цикл", proc.stderr)


if __name__ == "__main__":
    unittest.main()
