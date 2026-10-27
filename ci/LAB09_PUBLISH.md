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

## One-time Numba dependency migration

The Lab 09 update using Lab 08's compiled-loop technique adds only
`numba==0.68.0` and `llvmlite==0.50.0` to the rendering environment. All other
dependency versions stay fixed. Its affected set is the single Lab 09 notebook;
no other course member or PDF is rendered.

For this migration select `base_run_id=40448562994`,
`initialize_existing_release=false`, and `migrate_numba_dependencies=true`.
The workflow requires that exact successful run and commit
`06a14639016ae80ea529a6caa3bb17ff2f937aae`, verifies both retained artifacts,
and uses the `migrate-numba` operation. This operation requires the existing
state and release manifest, the pinned release's notebook source hash, and the
previous dependency hash
`b273cff9458e291b65e6fc710073f7c5e05a80fd9fecccbb87ac0f2d70c2bc03`.
It rejects any lock change beyond the two compiler packages. It then renders
Lab 09 once and records the new complete dependency hash only after successful
assembly. A failed render leaves the verified state unchanged.

After the migration use its successful run as the new base with both booleans
false. An unchanged update again renders zero members. The migration cannot be
reapplied to the migrated state; ordinary updates still reject dependency
changes. For local validation against a copy of the retained release:

```sh
python ci/publish_lab09.py migrate-numba --site /path/to/retained/site \
  --state /path/to/retained/lab09-state.json \
  --base-commit 06a14639016ae80ea529a6caa3bb17ff2f937aae \
  --report /path/to/migration-report.json
```

Run regressions with `python3 -m unittest discover -s ci -p 'test_*.py' -v`.
After publication verify the actual UCSD page and notebook download, including
the syllabus's November 2 deadline. A successful push alone is insufficient.
