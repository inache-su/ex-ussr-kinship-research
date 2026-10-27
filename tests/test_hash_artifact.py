"""Тесты hash_artifact.py: манифест многофайлового артефакта.

Запуск: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hash_artifact.py"


class HashDirectory(unittest.TestCase):
    def test_directory_manifest_is_sha256sum_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "A-0001-book"
            (folder / "frames").mkdir(parents=True)
            (folder / "frames" / "001.jpg").write_bytes(b"one")
            (folder / "manifest.json").write_text("{}", encoding="utf-8")
            (folder / ".DS_Store").write_bytes(b"noise")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(folder), "--json"],
                check=True, capture_output=True, text=True,
            )
            result = json.loads(proc.stdout)
            manifest = folder / "SHA256SUMS"
            self.assertEqual(result["files"], 2)
            self.assertEqual(result["sha256"], hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertEqual(
                manifest.read_text(encoding="utf-8").splitlines(),
                [
                    f"{hashlib.sha256(b'one').hexdigest()}  frames/001.jpg",
                    f"{hashlib.sha256(b'{}').hexdigest()}  manifest.json",
                ],
            )
            # Повторный запуск не включает сам манифест.
            subprocess.run([sys.executable, str(SCRIPT), str(folder)], check=True, capture_output=True)
            self.assertNotIn("SHA256SUMS", manifest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
