import json
from pathlib import Path
import tempfile
import unittest

from relocate_labs import relocate


class RelocateLabsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / "_build/html"
        (self.root / "redirects").mkdir()
        (self.root / "redirects/lab_pages.json").write_text(json.dumps({
            "labs/lab4/Lab4.html": "labs/lab05/lab05.html",
        }))
        self.old = self.site / "labs/lab4/Lab4.html"
        self.old.parent.mkdir(parents=True)
        self.old.write_text('Colab launch: labs/lab4/Lab4.ipynb')

    def test_replaces_stale_launch_page_and_preserves_current_page_and_manual_assets(self):
        new = self.site / "labs/lab05/lab05.html"
        new.parent.mkdir(parents=True)
        new.write_text("Current handout")
        manual = self.old.parent / "lecture.pdf"
        manual.write_bytes(b"manual slides")
        relocate(self.root, self.site)
        self.assertIn('content="0; url=../lab05/lab05.html"', self.old.read_text())
        self.assertNotIn("Lab4.ipynb", self.old.read_text())
        self.assertEqual(new.read_text(), "Current handout")
        self.assertEqual(manual.read_bytes(), b"manual slides")

    def test_missing_destination_fails_without_overwriting_old_page(self):
        with self.assertRaisesRegex(FileNotFoundError, "Missing current lab page"):
            relocate(self.root, self.site)
        self.assertIn("Lab4.ipynb", self.old.read_text())


if __name__ == "__main__":
    unittest.main()
