import hashlib
import html
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from relocate_labs import site_manifest, update_datahub_links


DATAHUB = (
    "https://datahub.ucsd.edu/hub/user-redirect/git-pull?"
    "repo=https%3A%2F%2Fgithub.com%2Fjmduarte%2Fphys142&branch=main&"
    "urlpath=tree%2Fphys142%2Flabs%2Flab08%2Flab08.ipynb&depth=1"
)
BINDER = "https://mybinder.org/v2/gh/jmduarte/phys142/main?urlpath=tree/labs/lab08/lab08.ipynb"


class LaunchMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.site = Path(temporary.name) / "html"
        self.site.mkdir()
        self.index = self.site / "index.html"
        self.index.write_bytes(b"<!doctype html>\n<title>Course</title>\n")

    def page(self, name, source):
        path = self.site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode("utf-8"))
        return path

    def snapshot(self):
        return {p.relative_to(self.site).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.site.rglob("*") if p.is_file()}

    def test_only_datahub_href_changes_and_unrelated_files_keep_bytes_and_mtimes(self):
        escaped = html.escape(DATAHUB, quote=True)
        source = (
            '<!doctype html>\r\n<p>π: notebook</p>\r\n'
            f'<a class="launch"\r\n href="{escaped}" data-other="{escaped}">DataHub</a>\r\n'
            f'<a href="{BINDER}">Binder</a>\r\n'
            f'<p>{escaped}</p>\r\n'
            f'<!-- <a href="{escaped}">example</a> -->\r\n'
            f'<pre><code><a href="{escaped}">example</a></code></pre>\r\n'
            f'<script>const example = \'<a href="{escaped}">\';</script>\r\n'
        )
        page = self.page("labs/lab08.html", source)
        self.page("labs/other.html", '<a href="/unrelated.html">Unchanged</a>')
        self.page("_sources/labs/lab08.ipynb", '{"cells": []}\n')
        self.page(".buildinfo", "existing build state\n")
        for p in self.site.rglob("*"):
            if p.is_file():
                os.utime(p, ns=(1_000_000_000, 1_000_000_000))
        before = self.snapshot()
        report = update_datahub_links(self.site, site_manifest(self.site))
        expected = source.replace(f'href="{escaped}"', f'href="{escaped.replace("urlpath=tree", "urlpath=lab%2Ftree")}"', 1)
        self.assertEqual(page.read_bytes(), expected.encode("utf-8"))
        after = self.snapshot()
        for name in before:
            if name != "labs/lab08.html":
                self.assertEqual(after[name], before[name], name)
        self.assertEqual(report["changed_files"], ["labs/lab08.html"])
        self.assertEqual(report["changed_pages"], 1)
        self.assertEqual(report["changed_links"], 1)
        self.assertEqual(report["output_manifest"], site_manifest(self.site))
        self.assertNotEqual(report["input_manifest"], report["output_manifest"])

    def test_rerun_with_current_manifest_changes_zero_files(self):
        self.page("lab.html", f'<a href="{DATAHUB}">DataHub</a>')
        first = update_datahub_links(self.site, site_manifest(self.site))
        before = self.snapshot()
        report = update_datahub_links(self.site, first["output_manifest"])
        self.assertEqual(report["changed_links"], 0)
        self.assertEqual(report["changed_pages"], 0)
        self.assertEqual(report["changed_files"], [])
        self.assertEqual(report["input_manifest"], report["output_manifest"])
        self.assertEqual(self.snapshot(), before)

    def test_query_encoding_and_notebook_target_preserved(self):
        for index, url in enumerate([
            DATAHUB,
            DATAHUB.replace("%2F", "%2f"),
            DATAHUB.replace("tree%2Fphys142%2Flabs%2Flab08%2Flab08.ipynb", "tree/phys142/labs/a%20b.ipynb"),
            DATAHUB.replace("urlpath=tree", "%75rlpath=t%72ee"),
            DATAHUB.replace("urlpath=tree", "urlpath=&#116;ree"),
        ]):
            with self.subTest(url=url):
                path = self.page(f"page{index}.html", f"<a HREF='{url}'>Launch</a>")
                update_datahub_links(self.site, site_manifest(self.site))
                result = html.unescape(path.read_text().split("HREF='", 1)[1].split("'", 1)[0])
                previous_query = parse_qs(urlsplit(html.unescape(url)).query)
                result_query = parse_qs(urlsplit(result).query)
                expected = dict(previous_query, urlpath=["lab/" + previous_query["urlpath"][0]])
                self.assertEqual(result_query, expected)
                self.assertEqual(urlsplit(result)._replace(query=""), urlsplit(html.unescape(url))._replace(query=""))

    def test_unrelated_launches_and_urls_are_not_modified(self):
        urls = [BINDER, DATAHUB.replace("jmduarte", "someone-else"),
                DATAHUB.replace("datahub.ucsd.edu", "example.org"),
                "https://datahub.ucsd.edu/hub/login", "/tree/phys142/lab.ipynb"]
        self.page("other.html", "\n".join(f'<a href="{url}">Link</a>' for url in urls))
        before = self.snapshot()
        report = update_datahub_links(self.site, site_manifest(self.site))
        self.assertEqual(report["changed_links"], 0)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_or_missing_manifest_fails_before_writing(self):
        self.page("first.html", f'<a href="{DATAHUB}">Launch</a>')
        expected = site_manifest(self.site)
        self.index.write_bytes(b"corrupt cached content")
        before = self.snapshot()
        for digest in (expected, "", None, "invalid"):
            with self.subTest(digest=digest):
                with self.assertRaises(ValueError):
                    update_datahub_links(self.site, digest)
                self.assertEqual(self.snapshot(), before)

    def test_missing_site_or_entrypoint_and_symlinks_are_rejected(self):
        with self.assertRaises(ValueError):
            site_manifest(self.site / "missing")
        self.index.unlink()
        with self.assertRaisesRegex(ValueError, "index.html"):
            site_manifest(self.site)
        self.index.write_text("restored")
        external = self.site.parent / "external"
        external.write_text("not an artifact file")
        (self.site / "linked.html").symlink_to(external)
        with self.assertRaisesRegex(ValueError, "symlink"):
            update_datahub_links(self.site, "0" * 64)
        self.assertEqual(external.read_text(), "not an artifact file")

    def test_malformed_targeted_query_fails_before_any_pages_are_written(self):
        self.page("a-valid.html", f'<a href="{DATAHUB}">Launch</a>')
        for malformed in [
            DATAHUB + "&urlpath=tree/phys142/other.ipynb",
            DATAHUB.replace("urlpath=", "missing="),
            DATAHUB + "&missing-equals",
            DATAHUB.replace("lab08.ipynb", "bad%ZZ.ipynb"),
            DATAHUB.replace("tree%2Fphys142", "tree%2Fother-repo"),
            DATAHUB.replace("lab08.ipynb", "..%2Flab08.ipynb"),
            DATAHUB + "&repo=https%3A%2F%2Fgithub.com%2Fjmduarte%2Fphys142",
        ]:
            with self.subTest(url=malformed):
                self.page("z-invalid.html", f'<a href="{malformed}">Launch</a>')
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    update_datahub_links(self.site, site_manifest(self.site))
                self.assertEqual(self.snapshot(), before)

    def test_manifest_contract_includes_hidden_files_and_relative_paths(self):
        self.page(".hidden", "state")
        expected = hashlib.sha256()
        for name in [".hidden", "index.html"]:
            digest = hashlib.sha256((self.site / name).read_bytes()).hexdigest()
            expected.update(name.encode() + b"\0" + digest.encode() + b"\n")
        self.assertEqual(site_manifest(self.site), expected.hexdigest())

    def test_cli_requires_expected_manifest(self):
        script = Path(__file__).with_name("migrate_launch_links.py")
        result = subprocess.run([sys.executable, str(script), "--site", str(self.site)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--expected-manifest", result.stderr)


if __name__ == "__main__":
    unittest.main()
