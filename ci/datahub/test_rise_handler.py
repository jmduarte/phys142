"""Regressions for Notebook and RISE sharing a filename but not a directory."""

from pathlib import Path
import tempfile
import unittest

from jupyter_server.auth import IdentityProvider
from jupyter_server.base.handlers import FileFindHandler
from jinja2 import DictLoader, Environment
from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application
from traitlets.config import Config

from phys142_rise import RootAwareFileFindHandler, configure


class StaticFileTests(AsyncHTTPTestCase):
    def get_app(self):
        FileFindHandler._static_paths.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for app in ("notebook", "rise"):
            (self.root / app).mkdir()
            (self.root / app / "bundle.js").write_text(f'window.app = "{app}";\n')
        (self.root / "private.txt").write_text("outside allowed static roots")
        return Application(
            [(rf"/{app}/(.*)", RootAwareFileFindHandler, {"path": str(self.root / app)})
             for app in ("notebook", "rise")],
            identity_provider=IdentityProvider(token="test-static-files"),
            cookie_secret="local-test-only",
            base_url="/",
            jinja2_env=Environment(loader=DictLoader({
                "403.html": "{{ message }}", "404.html": "{{ message }}",
            })),
        )

    def test_each_app_serves_its_own_bundle_after_the_other_app(self):
        for app in ("notebook", "rise", "notebook", "rise"):
            with self.subTest(app=app):
                response = self.fetch(f"/{app}/bundle.js")
                self.assertEqual(response.code, 200)
                self.assertEqual(response.body, f'window.app = "{app}";\n'.encode())
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_rise_can_be_requested_first(self):
        for app in ("rise", "notebook"):
            response = self.fetch(f"/{app}/bundle.js")
            self.assertEqual(response.code, 200)
            self.assertEqual(response.body, f'window.app = "{app}";\n'.encode())

    def test_outside_root_is_still_rejected(self):
        response = self.fetch("/rise/../private.txt")
        self.assertEqual(response.code, 404)
        self.assertNotIn(b"outside allowed static roots", response.body)

    def test_missing_asset_stays_missing_after_another_root_cached_it(self):
        (self.root / "notebook" / "notebook-only.js").write_text("private to notebook")
        self.assertEqual(self.fetch("/notebook/notebook-only.js").code, 200)
        self.assertEqual(self.fetch("/rise/notebook-only.js").code, 404)


class ConfigurationTests(unittest.TestCase):
    def test_preserves_settings_inherited_from_system_configuration(self):
        system = Config()
        system.ServerApp.tornado_settings = {"websocket_ping_interval": 17}
        user = Config()
        user.ServerApp.tornado_settings.update({"headers": {"X-Course": "phys142"}})
        configure(user)
        system.merge(user)
        self.assertEqual(system.ServerApp.tornado_settings["websocket_ping_interval"], 17)
        self.assertEqual(system.ServerApp.tornado_settings["headers"], {"X-Course": "phys142"})

    def test_refuses_an_explicit_custom_handler(self):
        class CustomHandler(FileFindHandler):
            pass
        config = Config()
        config.ServerApp.tornado_settings = {"static_handler_class": CustomHandler}
        with self.assertRaisesRegex(RuntimeError, "custom static handler"):
            configure(config)
        self.assertIs(config.ServerApp.tornado_settings["static_handler_class"], CustomHandler)


if __name__ == "__main__":
    unittest.main()
