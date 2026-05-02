# experiment-agent Roadmap

## v1.2.3 — Study manager session resume

**Status (2026-05-02)**: PR 1 (single-study, single-window, happy path)
in progress. Spec at
`docs/specs/2026-05-02-session-resume-design.md` (codex round 6 cleared,
2026-05-02). Plan at `docs/plans/2026-05-02-session-resume-implementation.md`
(10 tasks complete, ready for PR). Branch
`feat/v1.2.3-session-resume-spec`. Targets v1.1.0. PR 2 (hardening:
external-edit detection, multi-study, slug collision recovery,
explicit ethics-upgrade command, schema migration) deferred until ≥2
weeks of dogfood.

Add artifact-anchored session resume to `study_manager_agent` so
multi-week or multi-month human studies survive Claude session restarts.

**PR 1 scope (v1.1.0):**

- Artifact-anchored persistence: agent writes a Markdown + YAML
  frontmatter artifact on every state-changing turn
- `resume <study_id>` command rebuilds context from the artifact
- Stale-write detection via revision counter
- Prompt-injection guard for artifact body content
- Strict-precedence ethics derivation (derived field, not cached)
- IRB approval reconfirmation pass
- Runtime requirement: Read/Write/Edit tool access required

**PR 2 scope (v1.2.0, deferred):**

- External-edit detection (artifact edited externally with same revision)
- Vanished-file or moved-file recovery
- Multi-study concurrent in same workspace
- Explicit `ethics-upgrade` command
- Slug-collision resolution
- Auto-archive or garbage collection of old artifacts
- Schema migration tooling
