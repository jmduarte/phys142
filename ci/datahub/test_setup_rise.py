"""Installer integration tests; every configuration directory is temporary."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jupyter_server.base.handlers import FileFindHandler
from traitlets.config.loader import PyFileConfigLoader


HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "setup_rise.py"
SOURCE = HERE / "phys142_rise.py"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config_dir = self.root / "config with spaces"
        self.config = self.config_dir / "jupyter_server_config.py"
        self.module = self.config_dir / "phys142_rise.py"
        self.env = dict(os.environ, JUPYTER_CONFIG_DIR=str(self.config_dir))
        self.env.pop("JUPYTERHUB_DISABLE_USER_CONFIG", None)

    def run_installer(self, action, success=True):
        result = subprocess.run(
            [sys.executable, str(INSTALLER), action],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Refusing:", result.stderr)
        return result

    def write_config(self, content):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config.write_bytes(content)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): (
                path.read_bytes(), path.stat().st_mtime_ns
            )
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_install_copies_module_and_loads_through_traitlets(self):
        self.write_config(
            b"c = get_config()\nc.ServerApp.port = 8899\n"
            b"c.ServerApp.tornado_settings = {'websocket_ping_interval': 17}\n"
        )
        self.run_installer("install")
        self.assertEqual(self.module.read_bytes(), SOURCE.read_bytes())
        config = PyFileConfigLoader(self.config.name, path=str(self.config_dir)).load_config()
        self.assertEqual(config.ServerApp.port, 8899)
        settings = config.ServerApp.tornado_settings
        self.assertEqual(settings["websocket_ping_interval"], 17)
        self.assertTrue(issubclass(settings["static_handler_class"], FileFindHandler))
        self.assertIsNot(settings["static_handler_class"], FileFindHandler)

    def test_reinstall_does_not_rewrite_files(self):
        self.run_installer("install")
        before = self.snapshot()
        self.run_installer("install")
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_restores_original_bytes_and_later_outside_edits(self):
        original = b"c = get_config()\r\nc.ServerApp.port = 8899\r\n# no final newline"
        self.write_config(original)
        self.run_installer("install")
        addition = b"\n# Added independently later\nc.ServerApp.open_browser = False\n"
        self.config.write_bytes(self.config.read_bytes() + addition)
        self.run_installer("uninstall")
        self.assertEqual(self.config.read_bytes(), original + addition)
        self.assertFalse(self.module.exists())
        before = self.snapshot()
        self.run_installer("uninstall")
        self.assertEqual(self.snapshot(), before)

    def test_uninstall_removes_only_config_created_by_installer(self):
        self.run_installer("install")
        self.run_installer("uninstall")
        self.assertFalse(self.module.exists())
        self.assertFalse(self.config.exists())
        self.write_config(b"")
        self.run_installer("install")
        self.run_installer("uninstall")
        self.assertTrue(self.config.exists())
        self.assertEqual(self.config.read_bytes(), b"")

    def test_policy_block_creates_nothing(self):
        self.env["JUPYTERHUB_DISABLE_USER_CONFIG"] = "1"
        result = self.run_installer("install", success=False)
        self.assertIn("JUPYTERHUB_DISABLE_USER_CONFIG", result.stderr)
        self.assertFalse(self.config_dir.exists())

    def test_unowned_destination_is_never_replaced(self):
        self.write_config(b"# existing config\n")
        for content in (b"# someone else's module\n", SOURCE.read_bytes()):
            with self.subTest(content=content[:30]):
                self.module.write_bytes(content)
                before = self.snapshot()
                self.run_installer("install", success=False)
                self.assertEqual(self.snapshot(), before)
                self.run_installer("uninstall", success=False)
                self.assertEqual(self.snapshot(), before)

    def test_modified_owned_files_are_not_overwritten_or_removed(self):
        self.run_installer("install")
        original_config = self.config.read_bytes()
        original_module = self.module.read_bytes()
        for path, changed in (
            (self.module, original_module + b"\n# changed locally\n"),
            (self.config, original_config.replace(b"run_path(", b"run_path( # modified\n")),
        ):
            with self.subTest(path=path.name):
                self.config.write_bytes(original_config)
                self.module.write_bytes(original_module)
                path.write_bytes(changed)
                before = self.snapshot()
                self.run_installer("install", success=False)
                self.assertEqual(self.snapshot(), before)
                self.run_installer("uninstall", success=False)
                self.assertEqual(self.snapshot(), before)

    def test_invalid_python_config_is_not_changed(self):
        self.write_config(b"c = get_config()\nif broken syntax\n")
        before = self.snapshot()
        result = self.run_installer("install", success=False)
        self.assertIn("syntax", result.stderr.lower())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.module.exists())

    def test_symlinked_configuration_directory_is_refused(self):
        destination = self.root / "other"
        destination.mkdir()
        self.config_dir.symlink_to(destination, target_is_directory=True)
        result = self.run_installer("install", success=False)
        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual(list(destination.iterdir()), [])

    def test_symlinked_destination_files_are_refused(self):
        self.config_dir.mkdir()
        destination = self.root / "other.py"
        destination.write_bytes(b"# preserve me\n")
        for path in (self.config, self.module):
            with self.subTest(path=path.name):
                path.symlink_to(destination)
                before = self.snapshot()
                result = self.run_installer("install", success=False)
                self.assertIn("symlink", result.stderr.lower())
                self.assertEqual(self.snapshot(), before)
                path.unlink()


if __name__ == "__main__":
    unittest.main()
