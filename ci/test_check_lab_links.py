"""Exercise the published-link failures caused by notebook moves and omitted pages."""

from html import escape
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import quote, urlencode

from check_lab_links import audit_site


class PublishedLabLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.site = self.root / "_build/html"
        self.git("init", "--quiet")
        (self.root / "_toc.yml").write_text("root: README\nchapters:\n- file: labs/lab05/lab05.ipynb\n")
        self.write_site("index.html", '<a href="README.html">Course</a>')
        self.write_site("README.html", '<a href="labs/lab05/lab05.html">Lab 05</a>')
        self.notebook = "labs/lab05/lab05.ipynb"
        self.add_notebook(self.notebook)
        self.write_site("_sources/" + self.notebook, "{}")
        self.write_site("labs/lab05/lab05.html", self.launches(self.notebook) +
                        '<a href="../../_sources/labs/lab05/lab05.ipynb">Download</a>')

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True)

    def write_site(self, name, content):
        path = self.site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def add_notebook(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        self.git("add", "--", name)

    def launches(self, notebook):
        urls = [
            "https://mybinder.org/v2/gh/jmduarte/phys142/main?" + urlencode({"urlpath": "tree/" + notebook}),
            "https://colab.research.google.com/github/jmduarte/phys142/blob/main/" + quote(notebook),
            "https://datahub.ucsd.edu/hub/user-redirect/git-pull?" + urlencode({
                "repo": "https://github.com/jmduarte/phys142", "urlpath": "tree/phys142/" + notebook, "branch": "main"}),
        ]
        return "".join(f'<a href="{escape(url, quote=True)}">Launch</a>' for url in urls)

    def test_current_links_downloads_and_redirects_pass(self):
        self.write_site("labs/lab4/Lab4.html",
                        '<meta http-equiv="refresh" content="0; url=../lab05/lab05.html">'
                        '<a href="../lab05/lab05.html">Lab 05</a>')
        report = audit_site(self.root, self.site)
        self.assertEqual(report.errors, [])
        self.assertEqual(report.references, 7)

    def test_old_published_page_with_deleted_launch_targets_fails(self):
        self.write_site("labs/lab4/Lab4.html", self.launches("labs/lab4/Lab4.ipynb"))
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 3)
        self.assertTrue(all("labs/lab4/Lab4.ipynb" in error and "tracked notebook" in error for error in report.errors))

    def test_notebook_exists_but_generated_child_page_missing_fails(self):
        self.add_notebook("labs/reference/numba_ffmpeg/numba.ipynb")
        self.write_site("labs/reference/numba_ffmpeg/index.html", '<a href="numba.html">Numba</a>')
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("missing rendered target: labs/reference/numba_ffmpeg/numba.html", report.errors[0])

    def test_missing_download_fails(self):
        (self.site / "_sources" / self.notebook).unlink()
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("_sources/labs/lab05/lab05.ipynb", report.errors[0])

    def test_missing_toc_page_fails_when_sphinx_emits_no_link(self):
        self.add_notebook("labs/reference/numba_ffmpeg/numba.ipynb")
        (self.root / "_toc.yml").write_text(
            "root: README\nchapters:\n- file: labs/lab05/lab05.ipynb\n"
            "- file: labs/reference/numba_ffmpeg/numba.ipynb\n"
            "# - file: labs/unreleased/unreleased.ipynb\n"
        )
        self.write_site("labs/reference/numba_ffmpeg/index.html", '<span class="xref myst">Numba</span>')
        report = audit_site(self.root, self.site)
        self.assertEqual(report.errors, ["_toc.yml: missing rendered page: labs/reference/numba_ffmpeg/numba.html"])

    def test_untracked_notebook_does_not_validate_launch(self):
        self.git("rm", "--cached", "--", self.notebook)
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 3)

    def test_homepage_absolute_course_link_checked_and_external_links_ignored(self):
        self.write_site("README.html", '<a href="https://jduarte.physics.ucsd.edu/phys142/labs/lab4/Lab4.html">Old lab</a>'
                        '<a href="https://example.edu/labs/missing.html">Other course</a>'
                        '<a href="https://jduarte.physics.ucsd.edu/phys142/lectures/manual.pdf">Lecture</a>'
                        '<a href="https://colab.research.google.com/github/other/repo/blob/main/missing.ipynb">External notebook</a>')
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("README.html: missing rendered target: labs/lab4/Lab4.html", report.errors[0])

    def test_encoded_notebook_paths_and_html_escaped_query_strings(self):
        name = "labs/reference/an example.ipynb"
        self.add_notebook(name)
        self.write_site("labs/reference/example.html", self.launches(name))
        self.assertEqual(audit_site(self.root, self.site).errors, [])

    def test_broken_redirect_fails(self):
        self.write_site("labs/lab4/Lab4.html", '<meta http-equiv="refresh" content="0; url=../lab05/deleted.html">')
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("labs/lab05/deleted.html", report.errors[0])

    def test_malformed_course_launch_fails(self):
        self.write_site("labs/lab4/Lab4.html", '<a href="https://mybinder.org/v2/gh/jmduarte/phys142/main?urlpath=wrong">Launch</a>')
        report = audit_site(self.root, self.site)
        self.assertEqual(len(report.errors), 1)
        self.assertIn("launch link must have one urlpath", report.errors[0])


if __name__ == "__main__":
    unittest.main()
