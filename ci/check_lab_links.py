"""Reject broken lab navigation, downloads, and notebook launch links before publishing."""

import argparse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlsplit


REPOSITORY = "jmduarte/phys142"
SITE_HOSTS = {"jduarte.physics.ucsd.edu", "jmduarte.github.io"}
SITE_PREFIX = "/phys142/"


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "href" in attrs and attrs["href"]:
            self.links.append((attrs["href"], False))
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            match = re.search(r";\s*url\s*=\s*(.+)$", attrs.get("content", ""), re.I)
            if match:
                self.links.append((match.group(1).strip("\"' "), True))


def launch_notebook(url):
    """Return the course notebook target, None for unrelated URLs, or raise on malformed launches."""
    parts = urlsplit(url)
    path = unquote(parts.path)
    query = parse_qs(parts.query)
    if parts.hostname == "colab.research.google.com":
        prefix = f"/github/{REPOSITORY}/blob/"
        if not path.startswith(prefix):
            return None
        revision, separator, notebook = path[len(prefix):].partition("/")
        if not revision or not separator:
            raise ValueError("Colab link has no notebook path")
        return notebook
    if parts.hostname == "mybinder.org":
        if not path.startswith(f"/v2/gh/{REPOSITORY}/"):
            return None
        prefix = "tree/"
    elif parts.hostname == "datahub.ucsd.edu" and parts.path == "/hub/user-redirect/git-pull":
        repo = query.get("repo", [""])[0].removesuffix(".git").rstrip("/")
        if repo != f"https://github.com/{REPOSITORY}":
            return None
        prefix = f"tree/{REPOSITORY.split('/')[-1]}/"
    else:
        return None
    targets = query.get("urlpath", [])
    if len(targets) != 1 or not targets[0].startswith(prefix):
        raise ValueError(f"launch link must have one urlpath beginning with {prefix!r}")
    return targets[0][len(prefix):]


def local_target(url, page, site):
    parts = urlsplit(url)
    if parts.scheme and parts.scheme not in {"http", "https"}:
        return None
    path = unquote(parts.path)
    if parts.netloc:
        if parts.hostname not in SITE_HOSTS or not path.startswith(SITE_PREFIX):
            return None
        return (site / path[len(SITE_PREFIX):]).resolve()
    if not path:
        return None
    if path.startswith(SITE_PREFIX):
        return (site / path[len(SITE_PREFIX):]).resolve()
    return ((site if path.startswith("/") else page.parent) / path.lstrip("/")).resolve()


@dataclass
class AuditReport:
    pages: int = 0
    references: int = 0
    errors: list = field(default_factory=list)


def audit_site(root: Path, site: Path) -> AuditReport:
    root, site = root.resolve(), site.resolve()
    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.ipynb"], text=True
    ).split("\0")
    notebooks = {name for name in tracked if name and (root / name).is_file()}
    report = AuditReport()
    if not (site / "index.html").is_file():
        report.errors.append("index.html: missing rendered website entry point")
    # An unresolved Sphinx notebook reference may render as a span, with no href
    # to inspect. Require every released source to have its generated page too.
    toc = (root / "_toc.yml").read_text(encoding="utf-8")
    for source in re.findall(r"^\s*-\s+file:\s*([^#\n]+)", toc, re.MULTILINE):
        target = Path(source.strip().strip("\"' ")).with_suffix(".html")
        if not (site / target).is_file():
            report.errors.append(f"_toc.yml: missing rendered page: {target.as_posix()}")
    pages = sorted((site / "labs").rglob("*.html"))
    if not pages:
        report.errors.append("labs/: no rendered lab pages found")
    pages += [site / name for name in ("index.html", "README.html") if (site / name).is_file()]
    for page in pages:
        report.pages += 1
        parser = PageLinks()
        parser.feed(page.read_text(encoding="utf-8"))
        for url, redirect in dict.fromkeys(parser.links):
            source = page.relative_to(site).as_posix()
            try:
                notebook = launch_notebook(url)
                if notebook is not None:
                    report.references += 1
                    if notebook not in notebooks:
                        report.errors.append(f"{source}: launch target is not an existing tracked notebook: {notebook} ({url})")
                    continue
                target = local_target(url, page, site)
                if target is None:
                    continue
                relative = target.relative_to(site)
                if not (redirect or target.suffix == ".ipynb" or ("labs" in relative.parts and target.suffix == ".html")):
                    continue
                report.references += 1
                if not target.is_file():
                    report.errors.append(f"{source}: missing rendered target: {relative.as_posix()} ({url})")
            except ValueError as error:
                report.errors.append(f"{source}: invalid link {url!r}: {error}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--site", type=Path, help="Rendered website; defaults to ROOT/_build/html")
    args = parser.parse_args()
    report = audit_site(args.root, args.site or args.root / "_build/html")
    for error in report.errors:
        print(error, file=sys.stderr)
    print(f"Checked {report.references} lab references across {report.pages} HTML pages; {len(report.errors)} errors.")
    return bool(report.errors)


if __name__ == "__main__":
    sys.exit(main())
