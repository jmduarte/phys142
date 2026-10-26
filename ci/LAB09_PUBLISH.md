# Publish Lab 09 without rebuilding the course

Use **Publish Lab 09 incrementally** after committing the Lab 09 update with
`[skip ci]`. The normal deploy workflow rebuilds all HTML and is not appropriate
for this localized path.

The first-use migration is restricted to successful run `39826958218`, its
pinned archive digest and complete file-content manifest. Select that run and
enable `initialize_existing_release` exactly once. Later updates require a
successful run of this scoped workflow as `base_run_id`, with initialization
disabled. Both its `course-site` and `lab09-incremental-state` artifacts are
mandatory. Missing, corrupt or incompatible state stops publication.

The publisher hashes the notebook and its locked renderer dependencies. An
unchanged or revision-only update renders zero members. A content edit renders
only Lab 09, then updates that page's article/contents, downloadable unexecuted
notebook, generated figures, search terms and inventory title. It preserves
other course pages, shared assets and PDFs byte-for-byte. Release metadata does
not invalidate member content. The new full-site manifest and member hashes are
retained in the separate state artifact, independently of disposable build work.

Only Lab 09 and its publishing tools may differ from the selected base commit.
A renderer/dependency or other course-content change requires a separately scoped
migration; there is no cold-build or force-rebuild option. The workflow retains
the resulting HTML in the ordinary site cache, publishes both existing course
destinations and retains a complete reusable release.

Run regressions with `python3 -m unittest discover -s ci -p 'test_*.py' -v`.
After publication verify the actual UCSD page and notebook download, including
the syllabus's November 2 deadline. A successful push alone is insufficient.
