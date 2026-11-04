# ARS Integration Guide

How experiment-agent works with ARS (Academic Research Skills) pipeline. This file lives in experiment-agent repo. ARS requires zero modification.

## Principle

```
experiment-agent ──knows──> ARS handoff format
ARS ──does not know──> experiment-agent
User ──bridges──> between the two
```

## Reading ARS Stage 1 Output

When a user brings ARS Stage 1 (RESEARCH) output to experiment-agent, detect these section headings:

| Heading | Maps To |
|---------|---------|
| `## Research Question Brief` | plan mode step 1 (RQ + hypothesis), manage mode PLAN step 1 |
| `## Methodology Blueprint` | plan mode steps 2-4 (variables, design, methods), manage mode PLAN steps 2-4 |
| `## Annotated Bibliography` | Reference context (do not depend on; experiment-agent does not do lit review) |
| `## Synthesis Report` | Background context for experiment design |

**Detection method**: Loose heading matching. Do not depend on ARS schema version numbers. If headings are present, parse. If not, ask user for context.

## Producing ARS-Compatible Output

All experiment-agent outputs include a **Material Passport** header (ARS Schema 9):

```markdown
## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: [run | manage | validate | plan]
- Origin Date: [ISO 8601 timestamp]
- Verification Status: [UNVERIFIED | ANALYZED | VERIFIED]
- Version Label: [exp_result_v1 | study_status_v1 | validation_v1 | code_plan_v1 | study_protocol_v1]
```

**Verification Status rules:**
- `run` mode output → `UNVERIFIED` (results not yet validated)
- `manage` mode output → `UNVERIFIED` (data collected but not analyzed)
- `plan` mode output → `UNVERIFIED` (design artifact only; nothing has been executed yet)
- `validate` mode output without a successful reproducibility re-run → `ANALYZED` (statistical interpretation completed, but execution-level verification is absent, not applicable, or failed)
- `validate` mode output with a successful reproducibility re-run → `VERIFIED`
- Only upgrade a prior `run` artifact to `VERIFIED` after a successful reproducibility re-run. If re-run is skipped, not applicable, partial, or fails, keep the original artifact at `UNVERIFIED` and attach the separate validation report.

**Optional fields** (include when available):
- `Integrity Pass Date`: timestamp when validate mode completed
- `Upstream Dependencies`: version labels of artifacts this one depends on (e.g., if experiment used ARS Stage 1 RQ Brief)

## User Workflow: ARS → experiment-agent → ARS

```
1. User runs ARS Stage 1 (deep-research) → gets RQ Brief + Methodology Blueprint
2. User copies relevant sections to experiment-agent
3. experiment-agent: plan mode → run/manage mode → validate mode → produces results
4. User copies experiment_result / validation_report back to ARS
5. ARS asks about experiments; the user answers and enters the provenance entries
6. User starts ARS Stage 2 (academic-paper) with experiment results as input
```

The user is the bridge. No API calls, no automated handoff, no shared state.

## What ARS Asks at Intake

ARS asks every run whether the paper reports experiments or data analyses the scholar ran, and it records the scholar's own answer. Do not suggest skipping that question: ARS treats this skill's output as data for the scholar to confirm, not as an answer.

After a yes, the scholar enters one `experiment_provenance[]` entry per experiment. This skill does not fill them in ARS. Validate mode can give a draft (see `templates/output_formats.md`):

| ARS field | Who gives it |
|-----------|--------------|
| `experiment_id`, `title` | The researcher; the plan can suggest a title |
| `planned_vs_executed` | Draft from the plan and the experiment result; the researcher confirms and gives each `skip_reason` |
| `negative_results` | Draft from the validation report; the researcher confirms and adds what the report cannot see |
| `known_limitations` | Draft from the report and the plan; the researcher confirms and adds |
| `repro_lock` | The researcher. It records ARS version, model, prompt hashes and literature-search settings, which this skill does not know |

`repro_lock` was designed for LLM and artifact settings. For a study with no model, such as a survey, ARS does not yet say what to enter. Tell the researcher this, and do not invent hashes or versions.

## Passport Differences

This skill's passport uses Markdown labels, and ARS passports use YAML keys such as `origin_skill`. `Verification Status` also means different things:

| Value here | Meaning here |
|------------|--------------|
| `ANALYZED` | Statistical reading done. ARS has no such value |
| `VERIFIED` | A re-run reproduced the results. In ARS, `VERIFIED` means the artifact passed an ARS integrity check |

Do not copy these values into an ARS passport. ARS sets its own `verification_status`.
