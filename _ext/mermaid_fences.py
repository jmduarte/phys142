"""Render standard Mermaid fences with the course's pinned MyST parser.

MyST 0.18 requires directive braces, whereas Jupyter's Mermaid renderer expects
plain ``mermaid`` fences. Convert those code blocks to the Sphinx extension's
diagram nodes so the same notebook source renders in both tools.
"""

from docutils import nodes
from sphinxcontrib.mermaid import mermaid


def render_mermaid_fences(app, doctree):
    for block in list(doctree.findall(nodes.literal_block)):
        if block.get("language") != "mermaid":
            continue
        diagram = mermaid()
        diagram["code"] = block.astext()
        diagram["options"] = {}
        diagram.source, diagram.line = block.source, block.line
        block.replace_self(diagram)


def setup(app):
    app.setup_extension("sphinxcontrib.mermaid")
    app.connect("doctree-read", render_mermaid_fences)
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
