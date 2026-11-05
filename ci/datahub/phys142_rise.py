"""Keep Notebook and RISE static-file caches separate by search directory.

Jupyter Server 2.14.2 caches only the filename. Both applications ship a
bundle.js, so the first application's cached path can cause the second
application to return 403. Only path lookup changes here; Jupyter's original
root validation, authentication, and response headers remain inherited.
"""

import os

from jupyter_server.base.handlers import FileFindHandler
from jupyter_server.utils import filefind
from traitlets.config.loader import LazyConfigValue


class RootAwareFileFindHandler(FileFindHandler):
    """Resolve each filename within its own ordered static search roots."""

    _static_paths = {}

    @classmethod
    def get_absolute_path(cls, roots, path):
        key = (tuple(roots), path)
        with cls._lock:
            if key in cls._static_paths:
                return cls._static_paths[key]
            try:
                absolute_path = os.path.abspath(filefind(path, roots))
            except OSError:
                return ""  # The inherited handler turns a missing file into 404.
            cls._static_paths[key] = absolute_path
            return absolute_path


def configure(config):
    """Select the handler through ServerApp's supported Tornado settings hook."""
    settings = config.ServerApp.tornado_settings
    if not isinstance(settings, LazyConfigValue):
        current = settings.get("static_handler_class", FileFindHandler)
        if current not in (FileFindHandler, RootAwareFileFindHandler):
            raise RuntimeError("PHYS 142 RISE setup would replace a custom static handler; stop and review it.")
    # Keep this lazy when the config loader has not merged system settings yet.
    settings.update({"static_handler_class": RootAwareFileFindHandler})
