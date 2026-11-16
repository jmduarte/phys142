"""Regression checks for build reuse and dependency invalidation."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from build_cache import ASSIGNMENTS, build_keys


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "--quiet")
        self.notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": ["Original prose"]},
                {
                    "cell_type": "code", "metadata": {}, "source": ["print(1)"],
                    "execution_count": None, "outputs": [],
                },
            ],
        }
        files = {
            "README.md": "Course introduction",
            "_toc.yml": "root: README\n",
            "_config.yml": "execute:\n  execute_notebooks: cache\n",
            "environment.yml": "dependencies: [python]\n",
            "_ext/example.py": "SETTING = 1\n",
            "ci/build_cache.py": "# cache key helper\n",
            "ci/assemble_site.py": "# assembly helper\n",
            ".github/workflows/deploy.yml": "name: deploy\n",
            ".github/actions/cached-latex/action.yml": "name: cached-latex\n",
            "syllabus/syllabus.tex": "Syllabus",
            "syllabus/syllabus.bib": "@book{reference}",
            "syllabus/figure.png": "syllabus figure",
            "assignments/common/preamble.tex": "shared formatting",
            "labs/lab01/data.csv": "1,2,3\n",
            "labs/lab01/helper.py": "value = 1\n",
        }
        for document in ASSIGNMENTS:
            files[f"assignments/{document}/{document}.tex"] = document
        for name, content in files.items():
            self.write(name, content)
        self.write_notebook(self.notebook)
        self.git("add", ".")
        self.before = self.keys()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def write_notebook(self, notebook):
        self.write("labs/lab01/lab01.ipynb", json.dumps(notebook))

    def keys(self, image="texlive@sha256:original"):
        return build_keys(self.root, image)

    def assert_changed(self, expected):
        after = self.keys()
        self.assertEqual({key for key in after if after[key] != self.before[key]}, set(expected))

    def test_unchanged_content_ignores_timestamps(self):
        self.write("README.md", "Course introduction")
        self.assertEqual(self.keys(), self.before)

    def test_datahub_setup_changes_keep_all_course_build_caches(self):
        for name in ("ci/datahub/phys142_rise.py", "ci/datahub/setup_rise.py",
                     "ci/datahub/README.md", ".github/workflows/test-datahub-rise.yml"):
            self.write(name, "initial setup content\n")
            self.git("add", "--", name)
        self.assertEqual(self.keys(), self.before)
        self.write("ci/datahub/phys142_rise.py", "updated server setup\n")
        self.assertEqual(self.keys(), self.before)

    def test_assignment_edit_only_rebuilds_its_pdf(self):
        self.write("assignments/assignment2/assignment2.tex", "new question")
        self.assert_changed({"assignment2"})

    def test_shared_preamble_rebuilds_exactly_four_pdfs(self):
        self.write("assignments/common/preamble.tex", "new shared formatting")
        self.assert_changed(ASSIGNMENTS)

    def test_syllabus_source_does_not_rebuild_book(self):
        self.write("syllabus/syllabus.tex", "new syllabus")
        self.assert_changed({"syllabus"})

    def test_bibliography_is_a_site_and_syllabus_dependency(self):
        self.write("syllabus/syllabus.bib", "@book{new_reference}")
        self.assert_changed({"site", "syllabus"})

    def test_notebook_prose_keeps_execution_cache(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["cells"][0]["source"] = ["Updated classroom instructions"]
        self.write_notebook(notebook)
        self.assert_changed({"site"})

    def test_notebook_code_changes_code_key(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["cells"][1]["source"] = ["print(2)"]
        self.write_notebook(notebook)
        self.assert_changed({"site", "notebooks"})

    def test_notebook_outputs_do_not_invalidate_execution(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["cells"][1]["execution_count"] = 5
        notebook["cells"][1]["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
        self.write_notebook(notebook)
        self.assert_changed({"site"})

    def test_execution_metadata_changes_code_key(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["cells"][1]["metadata"]["tags"] = ["skip-execution"]
        self.write_notebook(notebook)
        self.assert_changed({"site", "notebooks"})

    def test_kernel_change_invalidates_execution_context(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["metadata"]["kernelspec"]["name"] = "julia"
        self.write_notebook(notebook)
        self.assert_changed({"site", "notebooks", "execution_context"})

    def test_notebook_execution_settings_invalidate_restore_prefix(self):
        settings = {
            "execution": {"timeout": 60},
            "mystnb": {"execution_timeout": 60},
            "tags": ["skip-execution"],
            "language_info": {"name": "python", "version": "3.10"},
        }
        for key, value in settings.items():
            with self.subTest(key=key):
                notebook = copy.deepcopy(self.notebook)
                notebook["metadata"][key] = value
                self.write_notebook(notebook)
                self.assert_changed({"site", "notebooks", "execution_context"})

    def test_notebook_display_metadata_retains_execution_cache(self):
        notebook = copy.deepcopy(self.notebook)
        notebook["metadata"]["title"] = "An edited lesson title"
        self.write_notebook(notebook)
        self.assert_changed({"site"})

    def test_data_and_library_changes_invalidate_execution_context(self):
        for name in ("labs/lab01/data.csv", "labs/lab01/helper.py", "environment.yml", "_ext/example.py"):
            with self.subTest(name=name):
                original = (self.root / name).read_text()
                self.write(name, original + "changed\n")
                self.assert_changed({"site", "execution_context"})
                self.write(name, original)

    def test_navigation_does_not_invalidate_execution(self):
        self.write("_toc.yml", "root: README\nchapters: [labs/lab01/lab01]\n")
        self.assert_changed({"site"})

    def test_removed_source_invalidates_its_pdf(self):
        self.git("rm", "--cached", "assignments/assignment1/assignment1.tex")
        self.assert_changed({"assignment1"})

    def test_renamed_source_invalidates_execution_context(self):
        self.git("mv", "labs/lab01/data.csv", "labs/lab01/renamed.csv")
        self.assert_changed({"site", "execution_context"})

    def test_new_tracked_root_data_is_an_execution_input(self):
        self.write("data/new.csv", "data\n")
        self.git("add", "data/new.csv")
        self.assert_changed({"site", "execution_context"})

    def test_untracked_outputs_are_excluded(self):
        self.write("syllabus/syllabus.pdf", "untracked PDF")
        self.write("_build/html/index.html", "untracked HTML")
        self.write("labs/lab01/untracked.csv", "local data")
        self.assertEqual(self.keys(), self.before)

    def test_private_gitlink_is_never_opened(self):
        self.git("update-index", "--add", "--cacheinfo", "160000," + "a" * 40 + ",assignments/private")
        # A broken symlink would raise if the helper attempted to read it.
        (self.root / "assignments/private").symlink_to("/missing/private/materials")
        self.assertEqual(self.keys(), self.before)
        self.git("update-index", "--cacheinfo", "160000," + "b" * 40 + ",assignments/private")
        self.assertEqual(self.keys(), self.before)

    def test_texlive_image_invalidates_all_pdf_keys_only(self):
        after = self.keys("texlive@sha256:changed")
        self.assertEqual({key for key in after if after[key] != self.before[key]}, {"syllabus", *ASSIGNMENTS})

    def test_latex_build_logic_invalidates_all_pdf_keys_only(self):
        self.write(".github/actions/cached-latex/action.yml", "changed compile commands")
        self.assert_changed({"syllabus", *ASSIGNMENTS})

    def test_assembly_changes_do_not_reexecute_or_recompile(self):
        self.write("ci/assemble_site.py", "changed assembly")
        self.assert_changed({"site"})

    def test_tests_are_not_build_inputs(self):
        self.write("ci/test_build_cache.py", "new test")
        self.write("tests/test_other.py", "new test")
        self.git("add", "ci/test_build_cache.py", "tests/test_other.py")
        self.assertEqual(self.keys(), self.before)

    def test_cli_emits_keys_and_appends_github_output(self):
        output = self.root / "github-output"
        output.write_text("existing=value\n")
        result = subprocess.run(
            [
                sys.executable, str(Path(__file__).with_name("build_cache.py")),
                "--root", str(self.root), "--texlive-image", "texlive@sha256:original",
                "--github-output", str(output),
            ],
            check=True, stdout=subprocess.PIPE, text=True,
        )
        self.assertEqual(dict(line.split("=", 1) for line in result.stdout.splitlines()), self.before)
        self.assertEqual(output.read_text(), "existing=value\n" + result.stdout)


if __name__ == "__main__":
    unittest.main()
