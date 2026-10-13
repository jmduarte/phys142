"""Replace obsolete published lab pages with their current page locations."""

import argparse
from html import escape
import json
from pathlib import Path, PurePosixPath
import posixpath


def relocate(root: Path, site: Path) -> None:
    moves = json.loads((root / "redirects/lab_pages.json").read_text())
    for old, new in moves.items():
        for name in (old, new):
            path = PurePosixPath(name)
            if path.parts[0] != "labs" or ".." in path.parts or path.suffix != ".html":
                raise ValueError(f"Invalid lab page path: {name}")
        if old == new or new in moves:
            raise ValueError(f"Lab relocation must point directly to a current page: {old}")
        if not (site / new).is_file():
            raise FileNotFoundError(f"Missing current lab page: {new}")

    # Validate every destination before replacing any previously published page.
    for old, new in moves.items():
        target = escape(posixpath.relpath(new, posixpath.dirname(old)), quote=True)
        page = site / old
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            '<!doctype html>\n<html lang="en">\n<head>\n'
            '  <meta charset="utf-8">\n'
            f'  <meta http-equiv="refresh" content="0; url={target}">\n'
            f'  <link rel="canonical" href="{target}">\n'
            '  <title>Lab page moved</title>\n</head>\n<body>\n'
            f'  <p><a href="{target}">Open the current lab page</a></p>\n'
            '</body>\n</html>\n'
        )
    print(f"Updated {len(moves)} previous lab URLs to their current pages.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--site", type=Path)
    args = parser.parse_args()
    relocate(args.root, args.site if args.site is not None else args.root / "_build/html")
