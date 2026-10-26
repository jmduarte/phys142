import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zlib

from relocate_labs import site_manifest


BASE_DOC = "labs/lab09/lab09"
HEADER = (b"# Sphinx inventory version 2\n# Project: Course\n"
          b"# Version: \n# The remainder of this file is compressed using zlib.\n")


def inventory(records):
    return HEADER + zlib.compress(("\n".join(records) + "\n").encode())


def search(docnames, titles, terms, titleterms):
    return "Search.setIndex(" + json.dumps({
        "docnames": docnames, "filenames": [d + ".ipynb" for d in docnames],
        "titles": titles, "terms": terms, "titleterms": titleterms,
        "objects": {}, "objtypes": {}, "objnames": {}, "envversion": {"sphinx": 56},
    }) + ")"


class PatchReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / "site"
        self.rendered = self.root / "rendered"
        self.site.mkdir()
        self.rendered.mkdir()
        self.notebook = self.root / "lab09.ipynb"
        self.notebook.write_text(json.dumps({"nbformat": 4, "cells": [
            {"cell_type": "code", "execution_count": None, "outputs": [], "source": ["1 + 1"]}
        ]}))
        self.write(self.site, "index.html", "<title>Course index</title>\n")
        self.write(self.site, "labs/other.html", "untouched lecture bytes\r\n")
        self.write(self.site, "_static/theme.css", "untouched styling")
        self.write(self.site, "labs/lab09/lab09.html", (
            '<html><head><title>Course</title></head><body><nav id="course">All labs</nav>'
            '<a href="https://datahub.example/lab09">Launch</a>'
            '<nav aria-label="Page"><ul><li>Old mobile TOC</li></ul></nav>'
            '<article class="bd-article"><h1>Old Lab</h1><p>Old content</p></article>'
            '<nav class="bd-toc-nav page-toc"><ul><li>Old desktop TOC</li></ul></nav>'
            '<footer>Course footer</footer></body></html>'
        ))
        self.write(self.rendered, "lab09.html", (
            '<html><body><nav id="course">Temporary standalone navigation</nav>'
            '<nav aria-label="Page"><ul><li>New mobile TOC</li></ul></nav>'
            '<article class="bd-article"><h1>New Lab</h1><p>Tunneling</p>'
            '<img src="_images/new.png" alt="result"></article>'
            '<nav class="bd-toc-nav page-toc"><ul><li>New desktop TOC</li></ul></nav>'
            '</body></html>'
        ))
        self.write(self.rendered, "_images/new.png", b"new plot bytes")
        self.write(self.rendered, "_images/unreferenced.png", b"do not publish")
        self.write(self.site, "_sources/labs/lab09/lab09.ipynb", '{"old":true}')
        self.write(self.site, "searchindex.js", search(
            ["before", BASE_DOC, "after"], ["Before", "Old Lab", "After"],
            {"old": 1, "shared": [0, 1, 2], "after": 2, "before": 0},
            {"old": 1, "shared": [0, 1]},
        ))
        self.write(self.rendered, "searchindex.js", search(
            ["lab09"], ["New Lab"], {"tunnel": 0, "shared": 0}, {"new": 0},
        ))
        self.write(self.site, "objects.inv", inventory([
            "before std:doc -1 before.html Before",
            BASE_DOC + " std:doc -1 " + BASE_DOC + ".html Old Lab",
            "after std:doc -1 after.html After",
        ]))
        self.write(self.rendered, "objects.inv", inventory([
            "lab09 std:doc -1 lab09.html New Lab",
        ]))
        for path in self.site.rglob("*"):
            if path.is_file():
                os.utime(path, ns=(1_000_000_000, 1_000_000_000))

    def write(self, directory, name, content):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)

    def snapshot(self):
        return {p.relative_to(self.site).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.site.rglob("*") if p.is_file()}

    def patch(self, manifest=None):
        script = Path(__file__).with_name("patch_lab09_release.py")
        self.assertTrue(script.is_file(), "Lab09 release patcher is not implemented")
        spec = importlib.util.spec_from_file_location("patch_lab09_release", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.patch_release(self.site, self.rendered, self.notebook,
                                    site_manifest(self.site) if manifest is None else manifest)

    def test_one_lab_changes_preserve_unrelated_bytes_mtimes_and_course_frame(self):
        before = self.snapshot()
        report = self.patch()
        page = (self.site / "labs/lab09/lab09.html").read_text()
        self.assertIn('<nav id="course">All labs</nav>', page)
        self.assertIn('href="https://datahub.example/lab09"', page)
        self.assertIn('<footer>Course footer</footer>', page)
        self.assertIn('src="../../_images/new.png"', page)
        self.assertIn("New mobile TOC", page)
        self.assertIn("New desktop TOC", page)
        self.assertNotIn("Old content", page)
        self.assertNotIn("Temporary standalone navigation", page)
        expected = {"labs/lab09/lab09.html", "_sources/labs/lab09/lab09.ipynb",
                    "_images/new.png", "searchindex.js", "objects.inv"}
        self.assertEqual(set(report["changed_files"]), expected)
        self.assertEqual((self.site / "_sources/labs/lab09/lab09.ipynb").read_bytes(), self.notebook.read_bytes())
        self.assertFalse((self.site / "_images/unreferenced.png").exists())
        after = self.snapshot()
        for name in before.keys() - expected:
            self.assertEqual(after[name], before[name], name)
        self.assertEqual(report["output_manifest"], site_manifest(self.site))

    def test_search_update_keeps_other_document_indices_and_term_membership(self):
        self.patch()
        index = json.loads((self.site / "searchindex.js").read_text()[16:-1])
        self.assertEqual(index["docnames"], ["before", BASE_DOC, "after"])
        self.assertEqual(index["filenames"], ["before.ipynb", BASE_DOC + ".ipynb", "after.ipynb"])
        self.assertEqual(index["titles"], ["Before", "New Lab", "After"])
        self.assertEqual(index["terms"], {"shared": [0, 1, 2], "after": 2, "before": 0, "tunnel": 1})
        self.assertEqual(index["titleterms"], {"shared": 0, "new": 1})
        records = zlib.decompress((self.site / "objects.inv").read_bytes().split(b"\n", 4)[4]).decode()
        self.assertEqual(records, "before std:doc -1 before.html Before\n"
                         + BASE_DOC + " std:doc -1 " + BASE_DOC + ".html New Lab\n"
                         + "after std:doc -1 after.html After\n")

    def test_repeating_same_update_changes_zero_files_and_preserves_mtimes(self):
        first = self.patch()
        before = self.snapshot()
        second = self.patch(first["output_manifest"])
        self.assertEqual(second["changed_files"], [])
        self.assertEqual(second["input_manifest"], second["output_manifest"])
        self.assertEqual(self.snapshot(), before)

    def test_standalone_thebe_kernel_path_cannot_replace_course_notebook_path(self):
        old = '<script type="text/x-thebe-config">{kernelOptions:{path:"./labs/lab09"}}</script>'
        new = '<script type="text/x-thebe-config">{kernelOptions:{path:"./."}}</script>'
        for directory, name, script in [(self.site, "labs/lab09/lab09.html", old),
                                        (self.rendered, "lab09.html", new)]:
            page = directory / name
            page.write_text(page.read_text().replace("</article>", script + "</article>"))
        self.patch()
        result = (self.site / "labs/lab09/lab09.html").read_text()
        self.assertIn(old, result)
        self.assertNotIn(new, result)

    def test_corrupt_or_absent_manifest_fails_before_any_write(self):
        expected = site_manifest(self.site)
        self.write(self.site, "index.html", "corrupt release")
        before = self.snapshot()
        for value in [expected, "", "nonsense"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.patch(value)
            self.assertEqual(self.snapshot(), before)

    def test_missing_or_unknown_html_structure_fails_before_any_write(self):
        self.write(self.rendered, "lab09.html", '<article class="bd-article">Missing TOCs</article>')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)

    def test_conflicting_existing_image_fails_before_any_write(self):
        self.write(self.site, "_images/new.png", b"different existing plot")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)

    def test_unknown_search_schema_fails_before_any_write(self):
        index = json.loads((self.rendered / "searchindex.js").read_text()[16:-1])
        index["alltitles"] = {}
        self.write(self.rendered, "searchindex.js", "Search.setIndex(" + json.dumps(index) + ")")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)

    def test_unrecognized_image_attribute_structure_fails_before_any_write(self):
        page = self.rendered / "lab09.html"
        page.write_text(page.read_text().replace('src="_images/new.png"', 'src=_images/new.png'))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)

    def test_nested_search_membership_is_rejected_before_any_write(self):
        index = json.loads((self.rendered / "searchindex.js").read_text()[16:-1])
        index["terms"]["invalid"] = [[0]]
        self.write(self.rendered, "searchindex.js", "Search.setIndex(" + json.dumps(index) + ")")
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)

    def test_executed_download_is_rejected_before_any_write(self):
        notebook = json.loads(self.notebook.read_text())
        notebook["cells"][0]["execution_count"] = 1
        self.notebook.write_text(json.dumps(notebook))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.patch()
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
