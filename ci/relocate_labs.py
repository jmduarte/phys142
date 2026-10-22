"""Finalize lab redirects and DataHub launch links in an already rendered site."""

import argparse
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import parse_qsl, unquote_plus, urlsplit


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


# Each sorted file contributes its UTF-8 relative POSIX path, NUL, ASCII
# SHA-256 hex digest, and LF. Include all files, including hidden files.
def site_manifest(site: Path) -> str:
    site = Path(site)
    if site.is_symlink() or not site.is_dir():
        raise ValueError("Existing website must be a directory, not a symlink")
    files = []
    for path in site.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Website contains a symlink: {path}")
        if path.is_file():
            files.append(path)
        elif not path.is_dir():
            raise ValueError(f"Website contains a nonregular file: {path}")
    if not (site / "index.html").is_file():
        raise ValueError("Existing website is missing index.html")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(site).as_posix()):
        name = path.relative_to(site).as_posix()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(name.encode("utf-8") + b"\0" + content_hash.encode("ascii") + b"\n")
    return digest.hexdigest()


_ATTRIBUTE = re.compile(
    r"(?P<name>[^\s\"'<>/=]+)(?:\s*=\s*(?:\"(?P<double>[^\"]*)\""
    r"|'(?P<single>[^']*)'|(?P<bare>[^\s\"'=<>`]+)))?"
)
_ENTITY = re.compile(r"&(#[0-9]+;?|#[xX][0-9a-fA-F]+;?|[^\t\n\f <&#;]{1,32};?)")
_COURSE_REPO = "https://github.com/jmduarte/phys142"


def _decoded_html(raw: str):
    """Decode HTML entities while retaining the original character offsets."""
    text, offsets, cursor = [], [], 0
    for match in _ENTITY.finditer(raw):
        text.append(raw[cursor:match.start()])
        offsets.extend(range(cursor, match.start()))
        token = match.group()
        decoded = unescape(token)
        text.append(decoded)
        offsets.extend(range(match.start(), match.end()) if decoded == token
                       else [match.start()] * len(decoded))
        cursor = match.end()
    text.append(raw[cursor:])
    offsets.extend(range(cursor, len(raw)))
    offsets.append(len(raw))
    return "".join(text), offsets


def _datahub_insertion(url: str):
    """Return the urlpath value offset and new prefix, or None if unchanged."""
    parts = urlsplit(url)
    if parts.hostname != "datahub.ucsd.edu" or parts.path != "/hub/user-redirect/git-pull":
        return None
    loose_query = parse_qsl(parts.query, keep_blank_values=True)
    repositories = [value.rstrip("/").removesuffix(".git") for key, value in loose_query if key == "repo"]
    if _COURSE_REPO not in repositories:
        return None
    if len(repositories) != 1:
        raise ValueError("Course DataHub link must have exactly one repo")
    if re.search(r"%(?![0-9a-fA-F]{2})", parts.query):
        raise ValueError("Course DataHub link has invalid percent encoding")
    pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, errors="strict")
    targets = [value for key, value in pairs if key == "urlpath"]
    if len(targets) != 1:
        raise ValueError("Course DataHub link must have exactly one urlpath")
    target = targets[0]
    prefix = "lab/tree/phys142/" if target.startswith("lab/") else "tree/phys142/"
    if not target.startswith(prefix):
        raise ValueError("Course DataHub urlpath must begin with tree/phys142/ or lab/tree/phys142/")
    notebook = target[len(prefix):]
    if (not notebook.endswith(".ipynb") or any(part in {"", ".", ".."} for part in notebook.split("/"))
            or "\\" in notebook or "?" in notebook or "#" in notebook):
        raise ValueError("Course DataHub link has an invalid notebook path")
    if prefix.startswith("lab/"):
        return None
    query_start = url.index("?") + 1
    cursor = 0
    for field in parts.query.split("&"):
        key, _, raw_value = field.partition("=")
        if unquote_plus(key) == "urlpath":
            # Match the existing slash encoding; retain the rest byte-for-byte.
            first_slash = re.match(r"tree(?P<slash>/|%2[fF])", raw_value)
            slash = first_slash.group("slash") if first_slash else "%2F"
            return query_start + cursor + len(key) + 1, "lab" + slash
        cursor += len(field) + 1
    raise ValueError("Course DataHub link has no urlpath field")


class _DataHubLinks(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.line_offsets = [0] + [match.end() for match in re.finditer("\n", source)]
        self.insertions = []
        self.example_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"pre", "code"}:
            self.example_depth += 1
        if self.example_depth:
            return
        raw_tag = self.get_starttag_text()
        name_end = re.match(r"<[^\s/>]+", raw_tag).end()
        hrefs = [match for match in _ATTRIBUTE.finditer(raw_tag, name_end)
                 if match.group("name").lower() == "href"]
        for match in hrefs:
            group = next((key for key in ("double", "single", "bare") if match.group(key) is not None), None)
            if group is None:
                continue
            url, raw_offsets = _decoded_html(match.group(group))
            insertion = _datahub_insertion(url)
            if insertion is not None:
                if len(hrefs) != 1:
                    raise ValueError("Course DataHub link has duplicate href attributes")
                index, prefix = insertion
                line, column = self.getpos()
                offset = self.line_offsets[line - 1] + column + match.start(group) + raw_offsets[index]
                self.insertions.append((offset, prefix))

    def handle_endtag(self, tag):
        if tag in {"pre", "code"}:
            self.example_depth = max(0, self.example_depth - 1)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def update_datahub_links(site: Path, expected_manifest: str) -> dict:
    """Change only course DataHub hrefs in a verified, already rendered site."""
    site = Path(site)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest or ""):
        raise ValueError("Expected manifest must be a lowercase SHA-256 digest")
    before = site_manifest(site)
    if before != expected_manifest:
        raise ValueError(f"Website manifest mismatch: expected {expected_manifest}, found {before}")
    edits = {}
    changed_links = 0
    for path in sorted(site.rglob("*.html")):
        source = path.read_bytes().decode("utf-8")
        parser = _DataHubLinks(source)
        try:
            parser.feed(source)
            parser.close()
        except ValueError as error:
            raise ValueError(f"{path.relative_to(site)}: {error}") from error
        if parser.insertions:
            for offset, prefix in reversed(parser.insertions):
                source = source[:offset] + prefix + source[offset:]
            edits[path] = source.encode("utf-8")
            changed_links += len(parser.insertions)
    # All pages must validate before any writes, including a check that the
    # reusable artifact did not change while its edits were being prepared.
    if site_manifest(site) != before:
        raise ValueError("Website changed while preparing the migration")
    for path, content in edits.items():
        path.write_bytes(content)
    return {
        "input_manifest": before,
        "output_manifest": site_manifest(site),
        "changed_pages": len(edits),
        "changed_links": changed_links,
        "changed_files": [path.relative_to(site).as_posix() for path in edits],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--site", type=Path)
    args = parser.parse_args()
    site = args.site if args.site is not None else args.root / "_build/html"
    relocate(args.root, site)
    print(json.dumps(update_datahub_links(site, site_manifest(site)), sort_keys=True))
