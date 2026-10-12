"""Add only the public PDFs selected by the course table of contents."""

import argparse
from pathlib import Path
import re
import shutil


HANDOUTS = ("assignment1", "assignment2", "assignment3", "final_projects")


def assemble(root: Path) -> None:
    html = root / "_build/html"
    if not (html / "index.html").is_file():
        raise FileNotFoundError("Build or restore the website before assembling PDFs")
    toc = (root / "_toc.yml").read_text()
    # A cached or previously assembled site must not retain a withdrawn handout.
    for name in HANDOUTS:
        (html / f"{name}.pdf").unlink(missing_ok=True)
    shutil.copy2(root / "syllabus/syllabus.pdf", html / "syllabus.pdf")
    for name in HANDOUTS:
        released = re.search(rf"^\s*- url: .*/{name}\.pdf", toc, re.MULTILINE)
        if released:
            shutil.copy2(root / f"assignments/{name}/{name}.pdf", html / f"{name}.pdf")
        print(f"{'released' if released else 'not released'}: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    assemble(parser.parse_args().root)
