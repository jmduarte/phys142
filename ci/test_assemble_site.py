import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from assemble_site import HANDOUTS, assemble


class ReleaseAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = self.root / "_build/html"
        self.html.mkdir(parents=True)
        (self.html / "index.html").write_text("course")
        (self.root / "syllabus").mkdir()
        (self.root / "syllabus/syllabus.pdf").write_bytes(b"syllabus")
        for name in HANDOUTS:
            folder = self.root / "assignments" / name
            folder.mkdir(parents=True)
            (folder / f"{name}.pdf").write_bytes(name.encode())
        (self.root / "_toc.yml").write_text("")

    def run_assembly(self):
        with contextlib.redirect_stdout(io.StringIO()):
            assemble(self.root)

    def test_only_uncommented_releases_are_published(self):
        (self.root / "_toc.yml").write_text(
            "    - url: https://example.edu/assignment1.pdf\n"
            "    # - url: https://example.edu/assignment2.pdf\n"
            "    - url: https://example.edu/final_projects.pdf\n"
        )
        self.run_assembly()
        self.assertEqual((self.html / "syllabus.pdf").read_bytes(), b"syllabus")
        self.assertEqual((self.html / "assignment1.pdf").read_bytes(), b"assignment1")
        self.assertEqual((self.html / "final_projects.pdf").read_bytes(), b"final_projects")
        self.assertFalse((self.html / "assignment2.pdf").exists())
        self.assertFalse((self.html / "assignment3.pdf").exists())

    def test_withdrawn_pdfs_removed_without_touching_other_content(self):
        for name in HANDOUTS:
            (self.html / f"{name}.pdf").write_bytes(b"old release")
        (self.html / "lecture.pdf").write_bytes(b"manual lecture")
        self.run_assembly()
        for name in HANDOUTS:
            self.assertFalse((self.html / f"{name}.pdf").exists())
        self.assertEqual((self.html / "lecture.pdf").read_bytes(), b"manual lecture")
        self.assertEqual((self.html / "index.html").read_text(), "course")

    def test_missing_released_pdf_fails(self):
        (self.root / "_toc.yml").write_text("- url: https://example.edu/assignment1.pdf\n")
        (self.root / "assignments/assignment1/assignment1.pdf").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_assembly()

    def test_missing_syllabus_fails(self):
        (self.root / "syllabus/syllabus.pdf").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_assembly()

    def test_missing_website_fails(self):
        (self.html / "index.html").unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_assembly()


if __name__ == "__main__":
    unittest.main()
