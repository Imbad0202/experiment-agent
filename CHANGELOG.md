# Changelog

## v1.2.0 (2026-09-25)

In `manage` mode, a study's validation and ethics status now come from a
program, when it can run, instead of the model's reading of the checklist,
and a study moves on to participant recruitment and data collection only
when that program reports READY.

Spec: [docs/specs/2026-09-24-study-state-checker-design.md](docs/specs/2026-09-24-study-state-checker-design.md).
Plan: [docs/plans/2026-09-24-study-state-checker-implementation.md](docs/plans/2026-09-24-study-state-checker-implementation.md).

### New: Study state checker (F-08)

- `scripts/check_study_state.py` reads a study state artifact and prints
  `result: VALID` with the derived ethics status and its reasons, or
  `result: INVALID` with one line per failed rule (V1-V10). It exits 0
  when valid, 1 when invalid, and 2 when it cannot run.
- `study_manager_agent` runs the checker after each write, when it
  validates an artifact, and before it reports or acts on an ethics
  status. If the checker cannot run, the agent says so, applies the rules
  by hand, and does not move a study from ETHICS to TRACK.
- After an IRB approval, the items in the reconfirmation set count only
  when they are answered again after the recorded approval time. The
  agent takes every time it records from the checker's `--now` option.
- Data goes to analysis only when the ethics status is READY. Collection
  can still be recorded as complete without it.
- `manage` mode now needs Python 3.9 or later and PyYAML to move a study
  into data collection. Both READMEs have a requirements section.

### Changed

- The skill's prompts were revised for current models (audit findings
  F-01 to F-07, F-09, F-10 and B-1). This covers how SKILL.md dispatches
  an agent, how statistical values read from unstructured output are
  confirmed with the user, the default tolerance for environment-sensitive
  reproducibility, and the ethics status wording in the templates.
- The artifact layout is strict. HTML, any heading other than the four
  section headings, a code fence not at the first column, code other than
  the one yaml block in Ethics Checklist Status or TRACK Log, a line
  nested or indented 16 or more columns deep, and a body line starting
  `$$` make an artifact INVALID. The spec names the readers whose display
  the checker matches (GitHub's file view, VS Code's preview and
  markdown-it), with one exception: inline math in VS Code's preview.
- The frontmatter and the yaml blocks are read strictly as well. YAML
  that the checker cannot read unambiguously is a parse error, for
  example a tag (such as `!!int`), a merge key (`<<`), a directive
  (`%YAML` or `%TAG`), a repeated key, or the line separators U+0085,
  U+2028 and U+2029; the spec lists the rest. The file must start with
  a line that is exactly `---`, with no byte order mark before it; no
  line up to the closing `---` may end with a lone CR; and no line inside
  the frontmatter may be one that a Markdown reader could take as its
  end, such as `---` indented by up to three spaces, or `...` alone on a
  line, however indented.
- A release check (`.github/workflows/release-discipline.yml`) runs on
  every push, pull request and version tag. It fails when the files that
  state the release version or date disagree.

### Fixed

- The version badge in both READMEs still showed 1.0, and the code runner
  agent's footer still said v1.0. Both now show the current version.
- The study state protocol said its list of out-of-scope behaviors was for
  v1.1.0. The list still applies, so that line no longer names a release.
- The 2026-05-02 session resume spec and plan use fictional names in
  their examples.

### Compatibility

- v1.2.0 checks study state files more strictly than v1.1.0 did,
  including files that v1.1.0 accepted and files edited by hand. A file
  that drifts from the documented schema (an unknown item ID, a status or
  event kind outside the documented values, a timestamp without offset),
  or that uses one of the layouts or YAML forms above, becomes INVALID
  with a message naming the problem, and the agent does not resume that
  study until the file is fixed or the study is recreated. After
  upgrading, run `python3 scripts/check_study_state.py <path-to-state.md>`
  from the skill's directory on each study state file before you resume
  the study.
- The derived status can be stricter for v1.1.0 artifacts, for example
  when reconfirmation after an approval is missing. It never becomes looser.
  For a study already in TRACK or COLLECT, the agent then tells the user
  that recruitment and data collection stop, and that no data goes to
  analysis, until the status is READY again.
- Without Python 3.9+ and PyYAML every mode still works, except that a
  study cannot move from ETHICS to TRACK.

### Still deferred

The session resume hardening that v1.1.0 listed as "deferred to v1.2.0"
is not in this release and has no target version: external-edit detection,
recovery of a vanished or moved file, several studies in one workspace, an
explicit `ethics-upgrade` command, slug-collision resolution, archiving old
artifacts, and schema migration.

## v1.1.0 (2026-05-02)

PR 2 (hardening: external-edit detection, multi-study, slug-collision
recovery, explicit ethics-upgrade command, schema migration) deferred
until ≥2 weeks of v1.1.0 dogfood evidence.

Spec: [docs/specs/2026-05-02-session-resume-design.md](docs/specs/2026-05-02-session-resume-design.md)
(codex round 6 cleared). Plan:
[docs/plans/2026-05-02-session-resume-implementation.md](docs/plans/2026-05-02-session-resume-implementation.md).

### New: Session resume for human studies

- `study_manager_agent` now persists study state to disk on every
  state-changing turn. Multi-week or multi-month studies survive Claude
  session restarts.
- New `resume <study_id>` command rebuilds context from the artifact at
  `./<study_id>/state.md` (or user-specified path).
- Artifact format: Markdown + YAML frontmatter, schema_version 1.
  Template at `templates/study_state.md`, worked example at
  `templates/study_state.example.md`.
- Ethics status is now **derived** from per-item state with strict
  precedence (NOT_YET_ASSESSED → ETHICS_BLOCKED → ETHICS_PENDING →
  READY), mirroring the rules at the top of
  `references/irb_ethics_checklist.md`. Frontmatter no longer stores
  ethics_status as a cached field.
- IRB approval transitions trigger a category-based reconfirmation pass
  (categories 1, 2.2-2.5, 3.4-3.6, 4 applicable, 5.2). See
  `references/study_state_protocol.md` "IRB approval reconfirmation set."
- Stale-write detection via revision counter. Two Claude sessions
  writing the same artifact are now safe: the second writer detects the
  revision change and refuses, asking the user how to resolve.
- Prompt-injection guard: artifact body content is treated as data
  describing the study, never as instruction directed at the agent.
- Runtime requirement: `resume` requires Read/Write/Edit tool access
  (Claude Code OK; chat-only runtimes do not get persistence).

### Out of scope for v1.1.0 (deferred to v1.2.0)

- External-edit detection (artifact edited externally with same revision)
- Vanished-file or moved-file recovery
- Multi-study concurrent in same workspace
- Explicit `ethics-upgrade` command
- Slug-collision resolution (v1.1.0 refuses + asks user)
- Auto-archive or garbage collection of old artifacts
- Schema migration tooling

### No breaking changes

- v1.0.1 users see no behavior change unless they invoke `resume` or
  start a study under the new persistence path
- Material Passport schema unchanged; ARS coupling unchanged
- `code_runner_agent` unchanged

## v1.0.1 (2026-05-02)

### Contract Fixes

- Clarified `validate` output semantics: `Verification Status` is now `ANALYZED` unless a successful reproducibility re-run upgrades it to `VERIFIED`
- Added Material Passport headers to `plan` mode templates (`code_experiment_plan.md`, `study_protocol.md`)
- Fixed reproducibility guidance for zero-baseline metrics by using a symmetric denominator with epsilon protection
- Reclassified hardware/OS-sensitive runs as `environment-sensitive` comparisons instead of blanket `not applicable`
- Added `CANNOT_VERIFY` and environment-sensitive cases to the documented validation/reproducibility output contract
- Tightened ethics gating so only `READY` can enter study tracking, while `ETHICS_PENDING` still blocks participant recruitment and data collection
- Relaxed consent wording to allow IRB-approved digital, implied, or waived consent paths where appropriate
- Corrected the chi-squared fallback guidance so Fisher's exact is limited to 2x2 tables

## v1.0 (2026-04-09)

### Initial Release

**New Skill: experiment-agent**

- 4 modes: `run` (code experiments), `manage` (human studies), `validate` (statistical interpretation + reproducibility), `plan` (Socratic experiment design)
- 2 agents: `code_runner_agent` (execute + monitor), `study_manager_agent` (plan + track)
- 5 reference protocols: stall detection, IRB ethics checklist, statistical interpretation (11-type fallacy scan), reproducibility verification, ARS integration guide
- 2 templates: code experiment plan, study protocol
- ARS-compatible Material Passport output (Schema 9)
- Independent operation + optional ARS pipeline integration (zero ARS modification)
- Source: Lu et al. (2026, *Nature* 651:914-919) Experiment Progress Manager concept

**Design decisions:**
- Executor + Monitor role only (no quality review — that's ARS reviewer's job)
- All anomaly detections are ADVISORY (user decides, except hard timeout)
- Statistical interpretation is descriptive (flags issues, does not make editorial recommendations)
- validate mode scope boundary: describes what numbers say, does not judge paper quality
- Single-direction ARS dependency: experiment-agent knows ARS format, ARS does not know experiment-agent
