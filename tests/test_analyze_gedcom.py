"""Тесты analyze_gedcom.py на синтетических данных без семейных сведений.

Запуск: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.analyze_gedcom import analyze, forbidden_periods, jdn, julian_easter, patronymic_fits, read_date

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "analyze_gedcom.py"


def indi(xref: str, name: str, sex: str = "M", birth: str = "", death: str = "", place: str = "") -> str:
    lines = [f"0 @{xref}@ INDI", f"1 NAME {name}", f"1 SEX {sex}"]
    if birth:
        lines += ["1 BIRT", f"2 DATE {birth}"]
    if death:
        lines += ["1 DEAT", f"2 DATE {death}"] + ([f"2 PLAC {place}"] if place else [])
    return "\n".join(lines) + "\n"


def fam(xref: str, husb: str, wife: str, children: list[str], marr: str = "") -> str:
    lines = [f"0 @{xref}@ FAM", f"1 HUSB @{husb}@", f"1 WIFE @{wife}@"] + [f"1 CHIL @{c}@" for c in children]
    if marr:
        lines += ["1 MARR", f"2 DATE {marr}"]
    return "\n".join(lines) + "\n"


def tree(*parts: str) -> str:
    return "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n1 CHAR UTF-8\n" + "".join(parts) + "0 TRLR\n"


class CalendarTest(unittest.TestCase):
    def test_julian_dates_and_easter(self) -> None:
        # Julian 1 Jan 1900 is Gregorian 13 Jan 1900; Julian 29 Feb 1900 exists.
        self.assertEqual(jdn(1900, 1, 1, True), jdn(1900, 1, 13, False))
        self.assertEqual(jdn(2000, 1, 1, False) - jdn(1, 1, 1, False), date(2000, 1, 1).toordinal() - 1)
        self.assertIsNotNone(read_date("29 FEB 1900", True))
        self.assertIsNone(read_date("29 FEB 1900", False))
        # Orthodox Easter: Gregorian 22 Apr 1900 and 5 May 2024.
        self.assertEqual(julian_easter(1900), (4, 9))
        self.assertEqual(jdn(2024, *julian_easter(2024), True), jdn(2024, 5, 5, False))

    def test_read_date_calendars(self) -> None:
        self.assertTrue(read_date("12 MAY 1890", True)["julian"])
        self.assertFalse(read_date("@#DGREGORIAN@ 12 MAY 1890", True)["julian"])
        self.assertTrue(read_date("JULIAN 12 MAY 1890", False)["julian"])
        self.assertFalse(read_date("12 MAY 1925", True)["julian"])
        self.assertIsNone(read_date("ABT 1890", True)["jdn"] if read_date("ABT 1890", True) else None)
        self.assertEqual(read_date("1890", True)["year"], 1890)

    def test_forbidden_periods_1900(self) -> None:
        names = {name for start, end, name in forbidden_periods(1900)
                 if start <= jdn(1900, 3, 1, True) <= end}
        self.assertEqual(names, {"Масленица (сырная седмица) и Великий пост"})
        easter = jdn(1900, *julian_easter(1900), True)
        self.assertFalse(any(s <= easter + 7 <= e for s, e, _ in forbidden_periods(1900)))  # Красная горка

    def test_patronymics(self) -> None:
        for father, patronymic in (("Иван", "Иванович"), ("Василий", "Васильевна"), ("Илья", "Ильич"),
                                   ("Павел", "Павлович"), ("Лев", "Львовна"), ("Михаил", "Михайлович"),
                                   ("Кузьма", "Кузьмин"), ("Пётр", "Петров"), ("Андрей", "Андреевич")):
            self.assertTrue(patronymic_fits(father, patronymic), (father, patronymic))
        self.assertFalse(patronymic_fits("Иван", "Петрович"))


class AnalyzeTest(unittest.TestCase):
    def test_findings(self) -> None:
        text = tree(
            indi("I1", "Пётр Иванович /Тестов/", birth="1870", death="2 JAN 1905", place="Деревня А"),
            indi("I2", "Анна /Тестова/", "F", birth="1872", death="10 JAN 1905", place="Деревня А"),
            indi("I3", "Иван Петрович /Тестов/", birth="1 MAY 1890", death="3 JUN 1891"),
            indi("I4", "Иван Петрович /Тестов/", birth="20 JUL 1892", death="20 JAN 1905", place="Деревня А"),
            indi("I5", "Мария Семёновна /Тестова/", "F", birth="1 JUN 1894"),
            indi("I6", "Анна Петровна /Тестова/", "F", birth="1895"),
            indi("I7", "Анна Петровна /Тестова/", "F", birth="1897"),
            fam("F1", "I1", "I2", ["I3", "I4", "I5", "I6", "I7"], marr="1 MAR 1890"),
        )
        found = analyze(text)["findings"]
        self.assertEqual(set(found), {"wedding_in_fast", "early_first_child", "replacement_name",
                                      "same_name_siblings", "patronymic_mismatch", "death_cluster"})
        self.assertIn("Великий пост", found["wedding_in_fast"][0]["detail"])
        self.assertIn("через 61 дн.", found["early_first_child"][0]["detail"])
        self.assertIn("I3", found["replacement_name"][0]["people"])
        self.assertIn("I6", found["same_name_siblings"][0]["people"])
        self.assertEqual(len(found["patronymic_mismatch"]), 1)
        self.assertIn("Семёновна", found["patronymic_mismatch"][0]["detail"])
        self.assertIn("3 смертей", found["death_cluster"][0]["detail"])

    def test_clean_tree_and_cutoff(self) -> None:
        text = tree(
            indi("I1", "Пётр /Тестов/", birth="1960"), indi("I2", "Анна /Тестова/", "F", birth="1962"),
            indi("I3", "Иван Семёнович /Тестов/", birth="1 MAY 1985"),
            fam("F1", "I1", "I2", ["I3"], marr="1 MAR 1985"),
        )
        self.assertEqual(analyze(text)["findings"], {})
        self.assertIn("patronymic_mismatch", analyze(text, before=2000)["findings"])
        wedding = tree(indi("I1", "Пётр /Тестов/"), indi("I2", "Анна /Тестова/", "F"),
                       fam("F1", "I1", "I2", [], marr="1 MAY 1900"))  # after Красная горка
        self.assertEqual(analyze(wedding)["findings"], {})

    def test_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tree.ged"
            path.write_text(tree(indi("I1", "Пётр /Тестов/"), indi("I2", "Анна /Тестова/", "F"),
                                 fam("F1", "I1", "I2", [], marr="10 DEC 1899")), encoding="utf-8")
            out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(path), "--json"],
                                 capture_output=True, check=True)
            result = json.loads(out.stdout.decode("utf-8"))
            self.assertIn("Рождественский пост", result["findings"]["wedding_in_fast"][0]["detail"])
            text_out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(path)], capture_output=True, check=True)
            self.assertIn("Венчание в пост", text_out.stdout.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
