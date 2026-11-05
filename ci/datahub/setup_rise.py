#!/usr/bin/env python3
"""Install or remove the PHYS 142 RISE fix in this user's Jupyter config."""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import tempfile

from jupyter_core.paths import jupyter_config_dir


BEGIN = b"# BEGIN PHYS142 RISE"
END = b"# END PHYS142 RISE"


class Refusal(Exception):
    """An existing setting or file prevents a safe change."""


def check_path(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise Refusal(f"unsafe symlink: {part}")


def read_file(path):
    check_path(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise Refusal(f"expected a regular file: {path}")
    return path.read_bytes()


def check_syntax(content, path):
    try:
        compile(content, str(path), "exec")
    except (SyntaxError, ValueError) as error:
        raise Refusal(f"invalid Python syntax in {path}: {error}") from error


def managed_block(module, digest, existed):
    # Own the added leading newline so removal preserves even an original file
    # without a final newline. ASCII escaping also supports non-UTF-8 configs.
    return (
        "\n# BEGIN PHYS142 RISE\n"
        f"# Existing config: {'yes' if existed else 'no'}\n"
        f"# Module SHA256: {digest}\n"
        f"__import__('runpy').run_path({ascii(str(module))})['configure'](get_config())\n"
        "# END PHYS142 RISE\n"
    ).encode("ascii")


def find_block(content, module, digest):
    if BEGIN not in content and END not in content:
        return None
    if content.count(BEGIN) == content.count(END) == 1:
        for existed in (False, True):
            block = managed_block(module, digest, existed)
            if block in content:
                return block, existed
    raise Refusal("the managed PHYS142 RISE block is damaged, modified, or from another version")


def write_file(path, content, expected):
    """Replace only the file we inspected, using a complete temporary file."""
    if read_file(path) != expected:
        raise Refusal(f"file changed during setup: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if expected is not None else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".phys142-rise-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
        if read_file(path) != expected:
            raise Refusal(f"file changed during setup: {path}")
        if expected is None:
            os.link(temporary, path)  # Exclusive creation; never replace a collision.
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def setup(action):
    if os.environ.get("JUPYTERHUB_DISABLE_USER_CONFIG"):
        raise Refusal("JUPYTERHUB_DISABLE_USER_CONFIG disables user configuration; ask the hub administrator")

    directory = Path(os.path.abspath(jupyter_config_dir()))
    check_path(directory)
    if directory.exists() and not directory.is_dir():
        raise Refusal(f"expected a configuration directory: {directory}")
    config = directory / "jupyter_server_config.py"
    module = directory / "phys142_rise.py"
    source_path = Path(__file__).resolve().with_name("phys142_rise.py")
    source = read_file(source_path)
    if source is None:
        raise Refusal(f"missing sibling module: {source_path}")
    check_syntax(source, source_path)
    digest = hashlib.sha256(source).hexdigest()
    existing_config = read_file(config)
    content = existing_config if existing_config is not None else b""
    check_syntax(content, config)
    existing_module = read_file(module)
    found = find_block(content, module, digest)
    if found is None and existing_module is not None:
        raise Refusal(f"unowned destination module already exists: {module}")
    if found is not None and existing_module != source:
        raise Refusal(f"installed module is missing, modified, or from another version: {module}")

    if action == "install":
        if found is not None:
            return f"Already installed in {directory}; no files changed."
        updated = content + managed_block(module, digest, existing_config is not None)
        check_syntax(updated, config)
        directory.mkdir(parents=True, exist_ok=True)
        write_file(module, source, None)
        try:
            write_file(config, updated, existing_config)
        except Exception:
            # Remove only our unchanged new module if the config write failed.
            if read_file(module) == source:
                module.unlink()
            raise
        return f"Installed in {directory}. Stop and restart your DataHub server to apply it."

    if found is None:
        return f"Not installed in {directory}; no files changed."
    block, existed = found
    updated = content.replace(block, b"", 1)
    check_syntax(updated, config)
    if updated or existed:
        write_file(config, updated, existing_config)
    else:
        config.unlink()
    module.unlink()
    return f"Removed from {directory}. Stop and restart your DataHub server to apply it."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall"))
    arguments = parser.parse_args()
    try:
        print(setup(arguments.action))
    except (Refusal, OSError) as error:
        parser.exit(1, f"Refusing: {error}\nNo package installations or upgrades were attempted.\n")


if __name__ == "__main__":
    main()
