# Publishing caches

The deploy workflow caches independent build results using tracked file contents.

- Website HTML is reused when its inputs are unchanged. A PDF-only edit skips
  Python and Julia setup entirely. Website changes regenerate HTML so navigation,
  search, and removed pages remain consistent.
- Notebook execution uses Jupyter Book's cache. Code edits rerun the changed
  notebook; prose edits reuse its outputs. Changes to shared code, data, execution
  configuration, or resolved Python/Julia dependencies invalidate execution reuse.
  The existing live-coding handouts remain excluded from execution.
- Python and Julia environments are cached independently. Dependencies are
  installed only on an exact environment-cache miss.
- Each PDF has its own cache. Its source directory, shared assignment preamble,
  build helper, and pinned TeX image determine its key. A lab edit does not compile
  PDFs or download TeX Live. Unreleased documents still compile when their inputs
  change, so they are checked before release.

Only tracked public inputs are fingerprinted. Private quiz submodules and local
build outputs are excluded. Notebook/data inputs are conservatively tracked
across the public source tree, including inactive labs. Cache eviction causes a
normal rebuild; a failed build does not substitute an older PDF or website.

HTML is cached **before** PDFs are assembled. `assemble_site.py` always applies
the current `_toc.yml` release rules and removes withdrawn handouts from the
assembled site. Pages receives the complete site. Department deployment compares
file checksums and preserves manually uploaded files; deletion remains limited
to the four controlled assignment/final-project PDFs.

Lab renames are recorded in `redirects/lab_pages.json`. After the book is built,
`relocate_labs.py` replaces the old published pages with redirects to the current
pages. This overwrites stale department-server HTML whose launch buttons would
otherwise point to deleted notebook filenames, while preserving uploaded PDFs.
Every destination must exist in the new build. `check_lab_links.py` then checks
rendered lab navigation, notebook downloads, and notebook launch paths before
either website is published.

DataHub launch links are finalized by `relocate_labs.py` to open each notebook
in JupyterLab (`lab/tree/phys142/...`) after the normal container selection and
repository update. Binder links keep their existing interface. The link check
covers lecture notebooks as well as labs and rejects classic DataHub links.
This presentation change is a site-only input; execution and PDF cache keys
stay unchanged.

The manual `Update DataHub links without rebuilding` workflow migrates the
successful Lab 08 release at `33c7d8b`. It requires that exact artifact and its
file-content manifest, rejects intervening course-content changes, and edits
only affected HTML link attributes. It never renders pages, executes notebooks,
or compiles PDFs. It also saves the resulting HTML under the current site cache
key, with released PDFs kept outside that cache as usual. An unavailable or
altered source artifact stops the migration. The migration commit uses
`[skip ci]` to avoid the ordinary build; dispatch this dedicated workflow for
publication. Future normal builds apply the same DataHub link transformation.

The Actions summary reports which PDFs and HTML were reused. Manual dispatch
with `rebuild_site=true` checks HTML rebuilding with the cached environments and
notebook results, without publishing (as with the previous manual workflow).
Increment `CACHE_EPOCH` in the workflow to refresh all environments and outputs.
When changing the TeX toolchain, update its digest-pinned `TEXLIVE_IMAGE` value.

Run the selection/release tests locally with:

```sh
python3 -m unittest discover -s ci -p 'test_*.py' -v
```
