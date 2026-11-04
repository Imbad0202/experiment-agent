# Experiment Agent

A Claude Code skill for experiment execution, monitoring, statistical interpretation, and reproducibility verification.

## Skill Overview

| Skill | Purpose | Key Modes |
|-------|---------|-----------|
| `experiment-agent` v1.2.0 | Execute + monitor experiments | run, manage, validate, plan |

## Routing Rules

1. **run vs manage**: run = code experiments (scripts, training, analysis). manage = human studies (surveys, interviews, field work). If unclear, ask user.
2. **validate**: Works on results from any source — this agent's outputs, external files, or ARS pipeline data. Does statistical interpretation + optional reproducibility re-run.
3. **plan**: Socratic dialogue to design experiments before running them. If user brings ARS Stage 1 output, pre-populates from RQ Brief and Methodology Blueprint.

## ARS Integration

- This skill works independently. No ARS dependency.
- When used with ARS: all outputs include a Material Passport header modeled on Schema 9.
- ARS requires zero modification. The user bridges manually.

## Key Rules

- All anomaly detections are ADVISORY (user decides)
- Only execute user-specified commands, except `manage` mode's read-only study state checker (`scripts/check_study_state.py`)
- Never auto-retry, never auto-kill (except hard timeout)
- Statistical interpretation is descriptive, not editorial
- Ethics checklist items are hard gates for human studies; `run` mode's participant data questions are a hard gate too
- Participant rows stay out of the conversation in every mode

## Version Info
- **Version**: 1.2.0
- **Last Updated**: 2026-09-25
- **Author**: Cheng-I Wu
- **License**: CC-BY-NC 4.0
