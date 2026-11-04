# Output Format Templates

All outputs use Markdown-based structured format with a Material Passport header (see `references/ars_integration_guide.md`). Planning templates in `code_experiment_plan.md` and `study_protocol.md` follow the same rule.

## Experiment Result (from run mode)

```markdown
## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: run
- Origin Date: [ISO 8601]
- Verification Status: UNVERIFIED
- Version Label: exp_result_v1

## Experiment Result

- **ID**: [unique id]
- **Type**: [training | analysis | etl | simulation | generic]
- **Status**: [completed | crashed | timeout | stopped_by_user]
- **Command**: [executed command]
- **Working Directory**: [path]
- **Duration**: [seconds]
- **Exit Code**: [int]
- **Participant Data**: [yes | no]
- **Ethics Basis**: [the user's stated approval or exemption | N/A]
- **Aggregate-Only Files**: [the files the user named | N/A]

### Output Files

| File | Size |
|------|------|
| [path] | [size] |

### Output Summary

[Auto-generated summary of structured output, if available. If Participant Data is yes, summarize only the Aggregate-Only Files]

### Anomalies Detected

[List of anomalies detected during monitoring, or "None"]
```

## Study Status (from manage mode)

```markdown
## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: manage
- Origin Date: [ISO 8601]
- Verification Status: UNVERIFIED
- Version Label: study_status_v1

## Study Status

- **ID**: [unique id]
- **Type**: [survey | experiment | field_study | interview | mixed]
- **Phase**: [planning | ethics_review | collecting | collected | paused]
- **Design**: [description]
- **Progress**: [current_n] / [target_n] ([completion_rate]%)
- **Timeline**: [start] to [expected_end] — [on_track | behind | ahead]

### Ethics Status

- **Status**: [NOT_YET_ASSESSED | ETHICS_BLOCKED | ETHICS_PENDING | READY]
- **Blocked Items**: [list or "None"]

### Risks

[List of detected risks with suggestions, or "None"]

### Data Readiness

- **Samples**: [n]
- **Missing Rate**: [rate]
- **Format Consistent**: [yes/no]
- **Ready for Analysis**: [yes/no]
- **Blockers**: [list or "None"]
```

## Validation Report (from validate mode)

```markdown
## Material Passport

- Origin Skill: experiment-agent
- Origin Mode: validate
- Origin Date: [ISO 8601]
- Verification Status: [ANALYZED | VERIFIED]
- Version Label: validation_v1

## Validation Report

- **Source**: [exp_id | external | manual_study]
- **Overall Flag Level**: [NO_FLAGS | CAUTION | RED_FLAG]

### Statistical Findings

| Metric | Test | Value | Effect Size | Flag |
|--------|------|-------|-------------|------|
| [name] | [test] | [stat, p] | [size, class] | [NO_FLAGS/CAUTION/RED_FLAG] |

### Warnings

| Type | Detail | Affected |
|------|--------|----------|
| [type] | [detail] | [metrics] |

### Fallacy Scan

- **Coverage**: [N]/11 fallacy types checked

| Fallacy | Severity | Detail | What to check |
|---------|----------|--------|---------------|
| [type] | [RED_FLAG/CAUTION/NOTE] | [detail] | [the number or assumption to look at; never what to write or report] |

### Reproducibility (if applicable)

- **Method**: [re-run deterministic | re-run stochastic | re-run environment-sensitive | not run | N/A]
- **Verdict**: [REPRODUCIBLE | PARTIALLY_REPRODUCIBLE | NOT_REPRODUCIBLE | CANNOT_VERIFY | N/A]

| Metric | Original | Re-run | Diff | Status |
|--------|----------|--------|------|--------|
| [name] | [value] | [value] | [diff] | [MATCH/WITHIN_TOLERANCE/MISMATCH] |

### ARS Provenance Draft (if the results go to ARS)

Draft for the researcher to check and enter in ARS. ARS treats it as data to confirm.

- **experiment_id**: [researcher chooses]
- **title**: [from the plan or the researcher]
- **planned_vs_executed**:
  - planned: [planned unit]; executed: [true | false]; skip_reason: [researcher fills, if executed is false]; result_file: [path, if any]
- **negative_results**:
  - [non-significant result or null finding]
- **known_limitations**:
  - [limitation on record]
- **repro_lock**: [researcher fills; see references/ars_integration_guide.md]
```

Include the ARS Provenance Draft only when the user says the results go to ARS. Take entries only from the plan, the experiment result, and this report. List every non-significant result under `negative_results` and every plan item, executed or skipped, under `planned_vs_executed`. If no plan is on record, ask the user what was planned. Do not fill `repro_lock`, and do not invent a reason or a limitation.
