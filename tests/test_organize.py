"""Round-trip safety tests. Run: python -m unittest discover -s tests -v"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "organize.py"
OLD = time.time() - 3 * 86400


def run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def snapshot(root: Path):
    """sha256 of every non-state file (names change, bytes must not)"""
    return sorted(hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in root.rglob("*") if p.is_file() and ".adhd-or-ocd" not in p.parts)


def make(root: Path, name, data=b"x", age=OLD):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    os.utime(p, (age, age))


def messy(root: Path):
    make(root, "Invoice Airtel (1).pdf", b"inv")
    make(root, "Copy of resume final FINAL v2.docx", b"cv")
    make(root, "Screenshot 2026-11-08 at 10.22.33.png", b"shot")
    make(root, "photo.JPG", b"photo-bytes")
    make(root, "photo copy.JPG", b"photo-bytes")      # exact duplicate
    make(root, "setup.exe", b"installer")
    make(root, "~$temp.docx", b"junk")
    make(root, "empty.txt", b"")
    make(root, "notes.md", b"hello")
    make(root, "Semester 3/unit 1 notes.pdf", b"unit1")
    make(root, "desktop.ini", b"[.ShellClassInfo]")
    make(root, "fresh.pdf", b"new", age=time.time())  # modified just now -> must be skipped
    make(root, "myapp/package.json", b"{}")           # project -> must be left alone
    make(root, "myapp/index.js", b"//")


class RoundTrip(unittest.TestCase):
    def sandbox(self):
        td = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(td.cleanup)
        root = Path(td.name) / "Messy"
        messy(root)
        return root

    def organize(self, mode):
        root = self.sandbox()
        before = snapshot(root)
        run("plan", root, "--mode", mode, "--depth", "2", "--prune-empty")
        run("apply", max((root / ".adhd-or-ocd").glob("plan-*.json")))
        self.assertEqual(before, snapshot(root), "files lost or changed")
        self.assertTrue((root / "myapp" / "package.json").exists(), "project folder was touched")
        self.assertTrue((root / "fresh.pdf").exists(), "recent file was moved")
        self.assertTrue((root / "desktop.ini").exists(), "system file was moved")
        return root

    def test_adhd_roundtrip_and_undo(self):
        root = self.organize("adhd")
        self.assertTrue((root / "_Sorted" / "Documents" / "notes.md").exists())
        self.assertTrue(any((root / "_Review" / "Duplicates").iterdir()))
        run("undo", root)
        self.assertTrue((root / "Invoice Airtel (1).pdf").exists())
        self.assertTrue((root / "Semester 3" / "unit 1 notes.pdf").exists())
        self.assertFalse((root / "_Sorted").exists(), "undo left empty folders behind")

    def test_ocd_roundtrip_and_undo(self):
        root = self.organize("ocd")
        self.assertTrue(list((root / "20_Areas" / "Finance").glob("invoice-airtel*.pdf")))
        self.assertTrue(list((root / "20_Areas" / "Career").glob("resume-final-final-v2*.docx")))
        self.assertTrue(list((root / "40_Media" / "Screenshots").rglob("*_screenshot.png")))
        run("undo", root)
        self.assertTrue((root / "Copy of resume final FINAL v2.docx").exists())
        self.assertFalse((root / "20_Areas").exists())

    def test_refuses_system_and_home(self):
        for bad in (Path.home(), Path(Path.home().anchor)):
            r = subprocess.run([sys.executable, str(SCRIPT), "scan", str(bad)], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)

    def test_scan_reports_score(self):
        info = json.loads(run("scan", self.sandbox(), "--json"))
        self.assertGreater(info["score"], 20)
        self.assertGreaterEqual(info["dup_files"], 1)


if __name__ == "__main__":
    unittest.main()
