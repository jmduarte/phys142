# DataHub RISE setup

Use this for a blank RISE slideshow whose browser console reports a 403 for
`static/rise/bundle.js` and whose error page says
`bundle.js is not in root static directory`.

Jupyter Server 2.14.2 caches static-file lookups by filename. Notebook 7 and
RISE both provide `bundle.js` in different directories. This setup selects a
handler that includes the search directories in the cache key. It inherits
Jupyter's path validation, authentication, and response headers unchanged.

## Install in your DataHub account

After getting these files from the course repository, run in a **DataHub
terminal**, from the repository root:

```sh
python ci/datahub/setup_rise.py install
```

The command copies the handler to your Jupyter configuration directory and
adds a marked block to `jupyter_server_config.py`. It preserves existing
settings outside that block and installs no packages. Pulling the repository
alone does not activate the fix, and this changes only your account.

1. Save your notebooks. Stopping the server ends running kernels and loses
   their in-memory variables.
2. In JupyterLab, select **File → Hub Control Panel**.
3. Select **Stop My Server**, then start your server again.
4. Open the notebook and choose **Open as Reveal Slideshow** from the
   command palette. A Markdown cell marked **Slide** should appear. Select a
   code cell and press **Shift+Enter** to check live execution.

A browser refresh or kernel restart does not reload server configuration.
The final acceptance check must happen on DataHub after the full server restart.

If setup refuses to proceed, retain its error and stop. In particular, a hub
that disables user configuration needs an administrator-side change. An existing
custom static handler also needs review before selecting this replacement.

## Remove

Use the same revision of the setup files that installed the fix:

```sh
python ci/datahub/setup_rise.py uninstall
```

Save work and stop/start your server again. Uninstall removes only the managed
block and its unchanged handler file. Later edits outside the block are retained.
The installer refuses altered files or a different installed revision instead
of overwriting them. To change revisions, uninstall with the original revision,
then install the reviewed new revision.

## Verification

These tests exercise real HTTP requests to the Jupyter handler, including both
asset request orders, missing assets, and rejected traversal. Installer tests
load actual Traitlets configuration and check preservation and removal behavior.

```sh
python -m pip install -r ci/datahub/requirements-test.txt
python -m unittest discover -s ci/datahub -p 'test_*.py' -v
```

The dependency file is for an isolated test environment, **not installation
into your running DataHub server**. The handler regression was reproduced with
Jupyter Server 2.14.2; browser validation uses JupyterLab 4.2.4, Notebook 7.2.1,
RISE 0.42.0, and ipywidgets 8.1.2.

These maintenance files live under `ci/`, which the course build already
excludes from website and notebook-execution fingerprints. Updating this setup
does not invalidate course rendering or notebook execution caches.

Sources: [Jupyter static-file handler](https://github.com/jupyter-server/jupyter_server/blob/v2.14.2/jupyter_server/base/handlers.py),
[configurable Tornado settings](https://github.com/jupyter-server/jupyter_server/blob/v2.14.2/jupyter_server/serverapp.py),
[extension static routes](https://github.com/jupyter-server/jupyter_server/blob/v2.14.2/jupyter_server/extension/application.py).
