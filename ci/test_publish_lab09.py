import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess

from relocate_labs import site_manifest


class Lab09PublicationStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'index.html').write_text('Unrelated course page')
        self.source = self.root / 'lab09.ipynb'
        self.source.write_text('{"cells": []}')
        self.state = self.root / 'persistent-state.json'
        self.dependency = 'a' * 64

    def initialize(self):
        from publish_lab09 import initialize_state
        initialize_state(self.site, self.state, site_manifest(self.site),
                         hashlib.sha256(self.source.read_bytes()).hexdigest(),
                         self.dependency)

    def forbidden_render(self, *_args):
        self.fail('An unchanged or invalid update must not render any member')

    def test_unchanged_and_revision_only_updates_render_zero_members(self):
        from publish_lab09 import update_member
        self.initialize()
        snapshot = (self.state.read_bytes(), (self.site / 'index.html').stat().st_mtime_ns)
        for _revision in range(2):
            self.source.touch()
            report = update_member(self.site, self.state, self.source, self.dependency,
                                   self.forbidden_render, self.forbidden_render)
            self.assertEqual(report['rendered_members'], 0)
            self.assertEqual(report['changed_files'], [])
        self.assertEqual(snapshot, (self.state.read_bytes(),
                                   (self.site / 'index.html').stat().st_mtime_ns))

    def test_one_member_edit_renders_once_and_persists_new_content_hash(self):
        from publish_lab09 import update_member
        self.initialize()
        self.source.write_text('{"cells": [{"source": "changed"}]}')
        calls = []
        def render(source):
            calls.append(source)
            rendered = self.root / 'rendered'
            rendered.mkdir()
            (rendered / 'lab09.html').write_text('New Lab 09')
            return rendered
        def assemble(site, rendered, source, expected_manifest):
            self.assertEqual(site_manifest(site), expected_manifest)
            (site / 'lab09.html').write_bytes((rendered / 'lab09.html').read_bytes())
            return {'changed_files': ['lab09.html'], 'output_manifest': site_manifest(site)}
        unrelated = (self.site / 'index.html').read_bytes()
        report = update_member(self.site, self.state, self.source, self.dependency, render, assemble)
        self.assertEqual(calls, [self.source])
        self.assertEqual(report['rendered_members'], 1)
        self.assertEqual((self.site / 'index.html').read_bytes(), unrelated)
        state = json.loads(self.state.read_text())
        self.assertEqual(state['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(state['site_manifest'], site_manifest(self.site))

    def test_missing_corrupt_or_incompatible_state_fails_before_rendering(self):
        from publish_lab09 import update_member
        for content in [None, '{}', 'not json']:
            with self.subTest(content=content):
                if self.state.exists():
                    self.state.unlink()
                if content is not None:
                    self.state.write_text(content)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    update_member(self.site, self.state, self.source, self.dependency,
                                  self.forbidden_render, self.forbidden_render)
        self.state.unlink()
        self.initialize()
        with self.assertRaises(ValueError):
            update_member(self.site, self.state, self.source, 'b' * 64,
                          self.forbidden_render, self.forbidden_render)
        (self.site / 'index.html').write_text('Corrupt retained release')
        with self.assertRaises(ValueError):
            update_member(self.site, self.state, self.source, self.dependency,
                          self.forbidden_render, self.forbidden_render)

    def test_initialization_is_explicit_and_does_not_overwrite_existing_state(self):
        from publish_lab09 import initialize_state
        self.initialize()
        original = self.state.read_bytes()
        with self.assertRaises(ValueError):
            initialize_state(self.site, self.state, site_manifest(self.site), 'b' * 64, self.dependency)
        self.assertEqual(self.state.read_bytes(), original)

    def test_numba_migration_renders_one_member_and_next_update_renders_zero(self):
        from publish_lab09 import migrate_numba_member, update_member
        self.dependency = 'b273cff9458e291b65e6fc710073f7c5e05a80fd9fecccbb87ac0f2d70c2bc03'
        self.initialize()
        previous_state = json.loads(self.state.read_text())
        unrelated = (self.site / 'index.html').read_bytes()
        calls = []
        def render(source):
            calls.append(source)
            return 'rendered with Numba'
        def assemble(site, rendered, source, expected_manifest):
            self.assertEqual(expected_manifest, previous_state['site_manifest'])
            (site / 'lab09.html').write_text(rendered)
            return {'changed_files': ['lab09.html'], 'output_manifest': site_manifest(site)}
        report = migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                      render, assemble)
        self.assertEqual(calls, [self.source])
        self.assertEqual(report['rendered_members'], 1)
        self.assertEqual((self.site / 'index.html').read_bytes(), unrelated)
        state = json.loads(self.state.read_text())
        self.assertEqual(state['dependency_sha256'], 'c' * 64)
        self.assertEqual(state['source_sha256'], previous_state['source_sha256'])
        report = update_member(self.site, self.state, self.source, 'c' * 64,
                               self.forbidden_render, self.forbidden_render)
        self.assertEqual(report['rendered_members'], 0)
        with self.assertRaises(ValueError):
            migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                 self.forbidden_render, self.forbidden_render)

    def test_numba_migration_rejects_missing_corrupt_and_wrong_prior_state(self):
        from publish_lab09 import migrate_numba_member
        for content in [None, '{}', 'not json']:
            with self.subTest(content=content):
                if self.state.exists():
                    self.state.unlink()
                if content is not None:
                    self.state.write_text(content)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                         self.forbidden_render, self.forbidden_render)
        self.state.unlink()
        self.initialize()
        with self.assertRaises(ValueError):
            migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                 self.forbidden_render, self.forbidden_render)
        state = json.loads(self.state.read_text())
        state['dependency_sha256'] = 'b273cff9458e291b65e6fc710073f7c5e05a80fd9fecccbb87ac0f2d70c2bc03'
        self.state.write_text(json.dumps(state))
        (self.site / 'index.html').write_text('Corrupt retained release')
        with self.assertRaises(ValueError):
            migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                 self.forbidden_render, self.forbidden_render)

    def test_failed_numba_render_keeps_verified_state(self):
        from publish_lab09 import migrate_numba_member
        self.dependency = 'b273cff9458e291b65e6fc710073f7c5e05a80fd9fecccbb87ac0f2d70c2bc03'
        self.initialize()
        before = self.state.read_bytes()
        def failed_render(_source):
            raise RuntimeError('Notebook execution failed')
        with self.assertRaises(RuntimeError):
            migrate_numba_member(self.site, self.state, self.source, 'c' * 64,
                                 failed_render, self.forbidden_render)
        self.assertEqual(self.state.read_bytes(), before)

    def test_numba_lock_migration_allows_only_pinned_additions(self):
        from publish_lab09 import verify_numba_lock
        previous = 'numpy==2.5.4\nscipy==1.18.1\n'
        additions = 'llvmlite==0.50.0\nnumba==0.68.0\n'
        verify_numba_lock(previous, additions + previous)
        for changed in [previous, previous + additions.replace('0.68.0', '0.67.0'),
                        additions + previous.replace('2.5.4', '2.5.3'),
                        additions + previous + 'extra==1.0\n',
                        additions + previous + 'numba==0.68.0\n']:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                verify_numba_lock(previous, changed)

    def test_unrelated_source_history_is_rejected(self):
        from publish_lab09 import verify_source_scope
        repo = self.root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-c', 'user.name=Test', '-c',
                                            'user.email=test@example.com', *args], cwd=repo)
        git('init', '-q')
        (repo / 'first').write_text('first history')
        git('add', 'first'); git('commit', '-qm', 'first')
        base = git('rev-parse', 'HEAD').decode().strip()
        git('checkout', '--orphan', 'unrelated')
        git('commit', '-qm', 'unrelated history')
        with self.assertRaises(ValueError):
            verify_source_scope(repo, base)


if __name__ == '__main__':
    unittest.main()
