"""Replace one verified release member using an independently rendered Lab 09.

This is a scoped release migration, not a substitute for incremental book state.
Only the Lab 09 article, page TOCs, download, images, and search/inventory records
can change. Every input is validated before any release member is written.
"""

import argparse
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import zlib

from relocate_labs import site_manifest


DOCNAME = "labs/lab09/lab09"
PAGE = DOCNAME + ".html"
DOWNLOAD = "_sources/" + DOCNAME + ".ipynb"
SEARCH_KEYS = {"docnames", "filenames", "titles", "terms", "objects", "objtypes",
               "objnames", "titleterms", "envversion"}


def _file(directory: Path, name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe release member: {name}")
    candidate = directory
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Symlink is not a release member: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"Missing release member: {candidate}")
    return candidate


class _Containers(HTMLParser):
    """Locate raw spans so the original course frame remains byte-identical."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_offsets = [0]
        for match in re.finditer("\n", source):
            self.line_offsets.append(match.end())
        self.active = []
        self.spans = {}
        self.feed(source)
        self.close()
        if self.active or set(self.spans) != {"article", "mobile", "desktop"}:
            raise ValueError("Lab page must contain exactly one article and both page TOCs")

    def source_offset(self):
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        for frame in self.active:
            if frame[1] == tag:
                frame[3] += 1
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        name = None
        if tag == "article" and "bd-article" in classes:
            name = "article"
        elif tag == "nav" and attributes.get("aria-label") == "Page":
            name = "mobile"
        elif tag == "nav" and {"bd-toc-nav", "page-toc"} <= classes:
            name = "desktop"
        if name:
            if name in self.spans or self.active:
                raise ValueError("Duplicate or nested Lab page containers")
            self.active.append([name, tag, self.source_offset(), 1])

    def handle_endtag(self, tag):
        completed = []
        for frame in self.active:
            if frame[1] == tag:
                frame[3] -= 1
                if frame[3] == 0:
                    end = self.source.find(">", self.source_offset())
                    if end < 0:
                        raise ValueError("Unclosed Lab page container")
                    self.spans[frame[0]] = (frame[2], end + 1)
                    completed.append(frame)
        for frame in completed:
            self.active.remove(frame)


_IMAGE_ATTRIBUTE = re.compile(
    r"(?P<prefix>\b(?:src|href)\s*=\s*)(?P<quote>[\"'])(?P<path>_images/[^\"']+)(?P=quote)",
    re.IGNORECASE,
)
_THEBE_CONFIG = re.compile(
    r"<script\b[^>]*\btype\s*=\s*([\"'])text/x-thebe-config\1[^>]*>.*?</script\s*>",
    re.IGNORECASE | re.DOTALL,
)


class _ImageReferences(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.count = 0
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "srcset":
                raise ValueError("Responsive image assets are outside the Lab 09 migration schema")
            if name in {"src", "href"} and value and value.startswith("_images/"):
                self.count += 1
            if (tag == "img" and name == "src" and value
                    and not value.startswith(("_images/", "https://", "http://", "data:"))):
                raise ValueError(f"Unsupported generated image reference: {value}")


def _page(base: str, rendered: str):
    base_spans = _Containers(base).spans
    rendered_spans = _Containers(rendered).spans
    replacements = []
    images = set()

    def image(match):
        relative = unescape(match["path"])
        path = PurePosixPath(relative)
        if (path.parts[0] != "_images" or len(path.parts) != 2
                or "\\" in relative or "?" in relative or "#" in relative):
            raise ValueError(f"Unsupported generated image path: {relative}")
        images.add(relative)
        return match["prefix"] + match["quote"] + "../../" + match["path"] + match["quote"]

    for name, (start, end) in base_spans.items():
        new_start, new_end = rendered_spans[name]
        replacement = rendered[new_start:new_end]
        if name == "article":
            old_configs = list(_THEBE_CONFIG.finditer(base[start:end]))
            new_configs = list(_THEBE_CONFIG.finditer(replacement))
            if len(old_configs) != len(new_configs) or len(old_configs) > 1:
                raise ValueError("Unexpected Lab 09 Thebe configuration structure")
            if old_configs:
                # The standalone renderer's kernel path is './.'. Retain the
                # course's configured notebook path rather than publishing it.
                config = new_configs[0]
                replacement = (replacement[:config.start()] + old_configs[0].group()
                               + replacement[config.end():])
        if _ImageReferences(replacement).count != len(list(_IMAGE_ATTRIBUTE.finditer(replacement))):
            raise ValueError("Unsupported generated image attribute structure")
        replacement = _IMAGE_ATTRIBUTE.sub(image, replacement)
        replacements.append((start, end, replacement))
    for start, end, replacement in sorted(replacements, reverse=True):
        base = base[:start] + replacement + base[end:]
    return base.encode("utf-8"), images


def _search(content: bytes, expected_docs=None):
    source = content.decode("utf-8")
    if not source.startswith("Search.setIndex(") or not source.endswith(")"):
        raise ValueError("Unsupported Sphinx search index wrapper")
    index = json.loads(source[16:-1])
    if not isinstance(index, dict) or set(index) != SEARCH_KEYS:
        raise ValueError("Unsupported Sphinx search index schema")
    documents = index["docnames"]
    if (not isinstance(documents, list) or not documents
            or any(not isinstance(item, str) for item in documents)
            or len(set(documents)) != len(documents)
            or (expected_docs is not None and documents != expected_docs)):
        raise ValueError("Unexpected Sphinx search document list")
    for field in ("filenames", "titles"):
        values = index[field]
        if (not isinstance(values, list) or len(values) != len(documents)
                or any(not isinstance(value, str) for value in values)):
            raise ValueError(f"Invalid Sphinx search field: {field}")
    if any(index[field] != {} for field in ("objects", "objtypes", "objnames")):
        raise ValueError("Object search indices are outside the Lab 09 migration schema")
    if not isinstance(index["envversion"], dict):
        raise ValueError("Invalid Sphinx search environment version")
    for field in ("terms", "titleterms"):
        if not isinstance(index[field], dict):
            raise ValueError(f"Invalid Sphinx search field: {field}")
        for term, value in index[field].items():
            ids = value if isinstance(value, list) else [value]
            if (not isinstance(term, str) or not ids
                    or any(type(item) is not int or not 0 <= item < len(documents) for item in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError(f"Invalid Sphinx search term membership: {term}")
    return index


def _merge_search(base: bytes, rendered: bytes) -> bytes:
    index = _search(base)
    update = _search(rendered, ["lab09"])
    if DOCNAME not in index["docnames"]:
        raise ValueError("Base search index is missing Lab 09")
    target = index["docnames"].index(DOCNAME)
    original = json.dumps(index, sort_keys=True)
    index["titles"][target] = update["titles"][0]
    for field in ("terms", "titleterms"):
        merged = {}
        for term in index[field].keys() | update[field].keys():
            existing = index[field].get(term, [])
            existing = existing if isinstance(existing, list) else [existing]
            members = sorted(set(item for item in existing if item != target)
                             | ({target} if term in update[field] else set()))
            if members:
                merged[term] = members[0] if len(members) == 1 else members
        index[field] = merged
    if json.dumps(index, sort_keys=True) == original:
        return base
    return ("Search.setIndex(" + json.dumps(index, sort_keys=True) + ")").encode("utf-8")


def _inventory(content: bytes):
    parts = content.split(b"\n", 4)
    if (len(parts) != 5 or parts[0] != b"# Sphinx inventory version 2"
            or not parts[1].startswith(b"# Project: ")
            or not parts[2].startswith(b"# Version: ")
            or parts[3] != b"# The remainder of this file is compressed using zlib."):
        raise ValueError("Unsupported Sphinx inventory schema")
    try:
        body = zlib.decompress(parts[4]).decode("utf-8")
    except (zlib.error, UnicodeError) as error:
        raise ValueError("Invalid compressed Sphinx inventory") from error
    if not body.endswith("\n"):
        raise ValueError("Sphinx inventory must have terminated records")
    records = body.splitlines()
    for line in records:
        fields = line.split(" ", 4)
        if len(fields) != 5 or not re.fullmatch(r"-?\d+", fields[2]):
            raise ValueError("Unsupported Sphinx inventory record")
    return b"\n".join(parts[:4]) + b"\n", records


def _merge_inventory(base: bytes, rendered: bytes) -> bytes:
    header, records = _inventory(base)
    _, updates = _inventory(rendered)
    old = [i for i, record in enumerate(records) if record.startswith(DOCNAME + " std:doc ")]
    new = [record for record in updates if record.startswith("lab09 std:doc ")]
    if len(old) != 1 or len(new) != 1:
        raise ValueError("Inventory requires exactly one Lab 09 document record")
    fields = records[old[0]].split(" ", 4)
    update = new[0].split(" ", 4)
    if fields[3] != PAGE or update[3] != "lab09.html":
        raise ValueError("Unexpected Lab 09 inventory destination")
    replacement = " ".join(fields[:4] + [update[4]])
    if replacement == records[old[0]]:
        return base
    records[old[0]] = replacement
    return header + zlib.compress(("\n".join(records) + "\n").encode("utf-8"))


def patch_release(site: Path, rendered: Path, notebook: Path, expected_manifest: str) -> dict:
    """Patch the verified site in place, preserving every unrelated file."""
    site, rendered, notebook = Path(site), Path(rendered), Path(notebook)
    if not isinstance(expected_manifest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest):
        raise ValueError("Expected release manifest must be a lowercase SHA-256 digest")
    before = site_manifest(site)
    if before != expected_manifest:
        raise ValueError(f"Release manifest mismatch: expected {expected_manifest}, found {before}")
    if rendered.is_symlink() or not rendered.is_dir() or notebook.is_symlink() or not notebook.is_file():
        raise ValueError("Rendered output and unexecuted notebook must be regular inputs")
    download = notebook.read_bytes()
    document = json.loads(download)
    if (not isinstance(document, dict) or document.get("nbformat") != 4
            or not isinstance(document.get("cells"), list)):
        raise ValueError("Download must be a version 4 notebook")
    for cell in document["cells"]:
        if (cell.get("cell_type") == "code"
                and (cell.get("execution_count") is not None or cell.get("outputs") != [])):
            raise ValueError("Published notebook download must remain unexecuted")
    base_page = _file(site, PAGE).read_bytes().decode("utf-8")
    rendered_page = _file(rendered, "lab09.html").read_bytes().decode("utf-8")
    page, images = _page(base_page, rendered_page)
    _file(site, DOWNLOAD)
    planned = {
        PAGE: page,
        DOWNLOAD: download,
        "searchindex.js": _merge_search(_file(site, "searchindex.js").read_bytes(),
                                        _file(rendered, "searchindex.js").read_bytes()),
        "objects.inv": _merge_inventory(_file(site, "objects.inv").read_bytes(),
                                        _file(rendered, "objects.inv").read_bytes()),
    }
    for name in sorted(images):
        content = _file(rendered, name).read_bytes()
        destination = site / name
        if destination.exists() and destination.read_bytes() != content:
            raise ValueError(f"Generated image conflicts with existing release: {name}")
        planned[name] = content
    if site_manifest(site) != before:
        raise ValueError("Release changed while preparing the Lab 09 update")
    changed = sorted(name for name, content in planned.items()
                     if not (site / name).exists() or (site / name).read_bytes() != content)
    for name in changed:
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(planned[name])
    return {"changed_files": changed, "input_manifest": before,
            "output_manifest": site_manifest(site)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--rendered", type=Path, required=True)
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--expected-manifest", required=True)
    args = parser.parse_args()
    print(json.dumps(patch_release(args.site, args.rendered, args.notebook,
                                   args.expected_manifest), sort_keys=True))


if __name__ == "__main__":
    main()
