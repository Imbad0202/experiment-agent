#!/usr/bin/env python3
"""Validate a study state artifact and derive its ethics_status.

Usage:
    python3 scripts/check_study_state.py <path-to-state.md>

Exit codes: 0 = VALID, 1 = INVALID, 2 = cannot run (reason on stderr).
Reads the artifact and references/study_state_protocol.md; writes nothing.
Rules: docs/specs/2026-09-24-study-state-checker-design.md
"""

import datetime
import decimal
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:  # main() reports this as exit 2
    yaml = None

PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "references" / "study_state_protocol.md"
ID_MAP_HEADING = "## Canonical checklist ID map"
ID_RE = re.compile(r"\d+\.\d+")

ITEM_STATUSES = ("PASS", "NEEDS_ACTION", "NOT_APPLICABLE")
IRB_STATUSES = ("NOT_YET_SUBMITTED", "SUBMITTED", "APPROVED", "EXEMPT")
PHASES = ("PLAN", "ETHICS", "TRACK", "COLLECT")
EVENT_KINDS = ("count_update", "timeline_change", "quality_issue", "agent_flag", "user_note")
REQUIRED_FIELDS = ("schema_version", "study_id", "created", "updated", "revision", "current_phase")
ETHICS_SECTION = "Ethics Checklist Status"
TRACK_SECTION = "TRACK Log"
REQUIRED_SECTIONS = ("Protocol Summary", ETHICS_SECTION, TRACK_SECTION)
# IRB approval reconfirmation set: these categories in full, plus these items.
RECONFIRM_CATEGORIES = (1, 4)
RECONFIRM_IDS = frozenset({"2.2", "2.3", "2.4", "2.5", "3.4", "3.5", "3.6", "5.2"})

# Rule names: the rule text in references/study_state_protocol.md § Validation rules.
V1 = "Missing frontmatter delimiters"
V2 = "Frontmatter is not parseable YAML"
V3 = "Required frontmatter field missing"
V4 = "`schema_version` is not a known version"
V5 = "`current_phase` is not in {PLAN, ETHICS, TRACK, COLLECT}"
V6 = "`revision` is not a positive integer"
V7 = "Required body section heading missing"
V8 = "Ethics Checklist Status YAML block is malformed"
V9 = "TRACK Log YAML block is malformed"
V10 = "Any timestamp is missing timezone"
NOT_TIMESTAMP = "is not an ISO 8601 date-time with offset (for example 2026-05-02T11:30:00+08:00)"

TIMESTAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2})"
)
BARE_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?")
FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})\s*(\S*)")
LINE_BREAK_RE = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")


class CannotRun(Exception):
    """The checker cannot produce a result (exit code 2)."""


class RosterItem(NamedTuple):
    item_id: str
    category: int
    category_name: str
    label: str


class Problem(NamedTuple):
    rule: str
    location: str
    detail: str


class Section(NamedTuple):
    heading: str
    line: int
    yaml_blocks: list  # (first content line number, text) of each yaml or yml fenced block
    open_fence: int = None  # line of a code fence still open at the end of the file; None when all close


class Result(NamedTuple):
    problems: list
    frontmatter: dict  # None when the frontmatter does not parse
    ethics: dict  # None unless the Ethics Checklist Status block parses
    status: str  # ethics_status; None when the artifact is invalid
    reasons: list

    @property
    def valid(self):
        return not self.problems


def load_roster(protocol_path=PROTOCOL_PATH):
    """Read the checklist roster (every ID except 5.1) from the protocol's ID map."""
    try:
        text = Path(protocol_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise CannotRun(f"cannot read the checklist ID map in {protocol_path}: {err}") from None
    lines = [line.rstrip() for line in text.split("\n")]
    if ID_MAP_HEADING not in lines:
        raise CannotRun(f"{protocol_path} has no '{ID_MAP_HEADING}' section")
    roster, seen = [], set()
    for line in lines[lines.index(ID_MAP_HEADING) + 1:]:
        if line.startswith("## "):
            break
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        item_id = cells[0]
        if not ID_RE.fullmatch(item_id):
            continue  # header or separator row
        if len(cells) < 3 or not cells[2]:
            raise CannotRun(f"the checklist ID map row for {item_id} has no label")
        if item_id in seen:
            raise CannotRun(f"the checklist ID map lists {item_id} more than once")
        seen.add(item_id)
        category = int(item_id.split(".")[0])
        if not 1 <= category <= 6:
            raise CannotRun(f"the checklist ID map puts {item_id} in category {category}; "
                            "the derivation rules classify only categories 1-6")
        if item_id != "5.1":  # 5.1 lives in the irb block
            roster.append(RosterItem(item_id, category, cells[1], cells[2]))
    if not roster:
        raise CannotRun("the checklist ID map has no item rows")
    return roster


def _string_loader():
    """A SafeLoader that leaves timestamps and decimal numbers as strings and rejects repeated keys."""
    class Loader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            # PyYAML keeps the last of repeated keys; the value it drops could be the blocking one.
            # Merge keys (<<) are expanded first, so a key that a merge brings in counts too.
            if isinstance(node, yaml.MappingNode):
                self.flatten_mapping(node)
                keys = set()
                for key_node, _ in node.value:
                    if not isinstance(key_node, yaml.ScalarNode):
                        continue  # complex keys fail in the base class
                    key = self.construct_object(key_node)
                    if key in keys:
                        raise yaml.constructor.ConstructorError(
                            None, None, f"found duplicate key {_q(key)}", key_node.start_mark)
                    keys.add(key)
            return super().construct_mapping(node, deep=deep)

    dropped = ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:float")
    Loader.yaml_implicit_resolvers = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag not in dropped]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return Loader


def load_yaml(text):
    """Parse YAML safely; timestamps stay strings and item IDs stay as written."""
    return yaml.load(text, Loader=_string_loader())


def parse_timestamp(value):
    """Return (aware datetime to the second, fraction of a second) for an ISO 8601 date-time
    with offset, else None. The pair orders instants exactly, digits past microseconds included."""
    if not isinstance(value, str):
        return None
    match = TIMESTAMP_RE.fullmatch(value)
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    if offset == "Z":
        tz = datetime.timezone.utc
    else:
        hours, minutes = int(offset[1:3]), int(offset[4:6])
        if hours > 23 or minutes > 59:
            return None
        sign = -1 if offset[0] == "-" else 1
        tz = datetime.timezone(sign * datetime.timedelta(hours=hours, minutes=minutes))
    try:
        moment = datetime.datetime(int(year), int(month), int(day), int(hour), int(minute),
                                   int(second or 0), tzinfo=tz)
    except ValueError:
        return None
    return moment, decimal.Decimal("0." + (fraction or "0"))


def _numbered_lines(text):
    """Split text into (line number, line) pairs; accepts CRLF and a leading BOM."""
    return [(number, line.removesuffix("\r"))
            for number, line in enumerate(text.removeprefix("\ufeff").split("\n"), start=1)]


def split_frontmatter(lines):
    """Return (frontmatter lines, body lines), or None when a delimiter is missing."""
    if not lines or lines[0][1].rstrip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index][1].rstrip() == "---":
            return lines[1:index], lines[index + 1:]
    return None


def _fence_opening(text):
    """Return (fence, info string) when the line opens a fenced code block."""
    match = FENCE_RE.match(text)
    if not match:
        return None
    fence, info = match.groups()
    if fence[0] == "`" and "`" in info:
        return None  # a backtick fence's info string cannot contain backticks
    return fence, info


def _fence_closes(text, fence):
    stripped = text.strip()
    return len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def split_sections(body):
    """Split body lines into '## ' sections, ignoring lines inside fenced code.

    Each section collects its yaml and yml fenced blocks, and the opening line of a
    fence still open at the end of the file. Returns (sections, hidden). hidden maps
    a '## ' heading found inside a fenced code block to (its line number, the line
    number where that block opened).
    """
    sections, hidden, fence, fence_line, block = [], {}, None, None, None
    for number, text in body:
        if fence:
            if _fence_closes(text, fence):
                if block is not None:
                    sections[-1].yaml_blocks.append((fence_line + 1, "\n".join(block)))
                fence = block = None
                continue
            if block is not None:
                block.append(text)
            if text.startswith("## "):
                hidden.setdefault(text[3:].rstrip(), (number, fence_line))
        else:
            opening = _fence_opening(text)
            if opening:
                fence, fence_line = opening[0], number
                if sections and opening[1].lower() in ("yaml", "yml"):
                    block = []
            elif text.startswith("## "):
                sections.append(Section(text[3:].rstrip(), number, []))
    if fence and sections:
        sections[-1] = sections[-1]._replace(open_fence=fence_line)
    return sections, hidden


def _oneline(text):
    """Escape control characters and line separators so text stays on one line."""
    return LINE_BREAK_RE.sub(lambda match: "\\u%04x" % ord(match.group()), text)


def _q(value):
    """Show an artifact value in a problem detail: strings quoted, one line, short."""
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    if not isinstance(value, str):
        return _oneline(json.dumps(value, default=str))
    if len(value) > 80:
        value = value[:77] + "..."
    return _oneline(json.dumps(value, ensure_ascii=False))


def _show(value):
    """Show a value as-is when it is one line of printable characters, else like _q."""
    if isinstance(value, str) and value.isprintable():
        return value
    return _q(value)


def _parse_yaml(text, first_line, not_mapping):
    """Return (mapping, None), or (None, detail) naming the file line of a YAML error."""
    try:
        data = load_yaml(text)
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        problem = getattr(err, "problem", None) or str(err).split("\n")[0]
        where = f" (line {first_line + mark.line})" if mark is not None else ""
        return None, f"YAML does not parse: {problem}{where}"
    return (data, None) if isinstance(data, dict) else (None, not_mapping)


def _string_leaves(value, path, seen):
    """Yield (path, text) for every string in value, visiting each container once."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, (dict, list)) and id(value) not in seen:
        seen.add(id(value))  # YAML aliases can repeat one container many times
        if isinstance(value, dict):
            for key, child in value.items():
                yield from _string_leaves(child, f"{path}.{key}", seen)
        else:
            for index, child in enumerate(value):
                yield from _string_leaves(child, f"{path}[{index}]", seen)


def flag_bare_datetimes(value, path, problems, skip=()):
    """V10 for other fields: a string that is just a date and a time has no offset."""
    for where, text in _string_leaves(value, path, set()):
        if where not in skip and BARE_DATETIME_RE.fullmatch(text):
            problems.append(Problem(V10, where, f"{_q(text)} is a date and time without an offset"))


def _present(value):
    return value is not None and value != ""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_choice(value, rule, location, choices, problems):
    """Report a value that is missing or not one of the documented choices."""
    if value is None:
        problems.append(Problem(rule, location, "is missing"))
    elif value not in choices:
        problems.append(Problem(rule, location, f"{_q(value)} is not one of {', '.join(choices)}"))


def _check_timestamp(value, location, problems):
    """V10 for a timestamp field: a value that is set must be a date-time with an offset."""
    if value is not None and parse_timestamp(value) is None:
        problems.append(Problem(V10, location, f"{_q(value)} {NOT_TIMESTAMP}"))


def check_frontmatter(frontmatter, problems):
    """Apply V3-V6 and V10 to a parsed frontmatter mapping."""
    for field in REQUIRED_FIELDS:
        if not _present(frontmatter.get(field)):
            problems.append(Problem(V3, f"frontmatter.{field}", "is missing or empty"))
    version = frontmatter.get("schema_version")
    if _present(version) and not (_is_int(version) and version == 1):
        problems.append(Problem(V4, "frontmatter.schema_version", f"{_q(version)} is not 1"))
    if _present(frontmatter.get("current_phase")):
        _check_choice(frontmatter["current_phase"], V5, "frontmatter.current_phase", PHASES, problems)
    revision = frontmatter.get("revision")
    if _present(revision) and not (_is_int(revision) and revision >= 1):
        problems.append(Problem(V6, "frontmatter.revision", f"{_q(revision)} is not a positive integer"))
    for field in ("created", "updated"):
        value = frontmatter.get(field)
        if _present(value):  # an empty value is reported under V3 only
            _check_timestamp(value, f"frontmatter.{field}", problems)
    summary = frontmatter.get("track_summary")
    if isinstance(summary, dict):
        _check_timestamp(summary.get("last_event_ts"), "frontmatter.track_summary.last_event_ts", problems)
    flag_bare_datetimes(frontmatter, "frontmatter", problems, skip={
        "frontmatter.created", "frontmatter.updated", "frontmatter.track_summary.last_event_ts"})


def _section_block(sections, hidden, name, rule, keys, problems):
    """Parse the one yaml block of the named section; record why when that fails."""
    found = [section for section in sections if section.heading == name]
    if not found:
        return None  # reported under V7
    where = f"## {name}"
    if len(found) > 1:
        lines = ", ".join(str(section.line) for section in found)
        problems.append(Problem(rule, where, f"section appears {len(found)} times "
                                f"(lines {lines}); it must appear once"))
        return None
    if name in hidden:
        problems.append(Problem(rule, where, "another heading for this section on line %d is inside a code "
                                "block opened on line %d; the section must appear once" % hidden[name]))
        return None
    if found[0].open_fence:
        problems.append(Problem(rule, where, f"a code block opened on line {found[0].open_fence} "
                                "is never closed"))
        return None
    blocks = found[0].yaml_blocks
    if len(blocks) != 1:
        problems.append(Problem(rule, where, f"section has {len(blocks) or 'no'} yaml blocks; "
                                "it must have exactly one"))
        return None
    first_line, text = blocks[0]
    data, error = _parse_yaml(text, first_line, f"the yaml block must be a mapping with {keys}")
    if error:
        problems.append(Problem(rule, where, error))
    return data


def check_ethics(ethics, roster, problems):
    """Apply V8 and V10 to a parsed Ethics Checklist Status block."""
    roster_ids = {item.item_id for item in roster}
    items = ethics.get("items")
    if not isinstance(items, list):
        problems.append(Problem(V8, "ethics.items", "must be a list (use [] when empty)"))
        items = []
    seen_ids = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(Problem(V8, f"ethics.items[{index}]", "must be a mapping with id and status"))
            continue
        item_id = item.get("id")
        usable = isinstance(item_id, str) and ID_RE.fullmatch(item_id)
        where = f"ethics.items[{item_id if usable else index}]"
        if item_id is None:
            problems.append(Problem(V8, f"{where}.id", "is missing"))
        elif item_id == "5.1":
            problems.append(Problem(V8, f"{where}.id", "5.1 belongs in the irb block, not in items"))
        elif not isinstance(item_id, str) or item_id not in roster_ids:
            problems.append(Problem(V8, f"{where}.id", f"{_q(item_id)} is not in the checklist ID map"))
        elif item_id in seen_ids:
            problems.append(Problem(V8, f"{where}.id", f"{_q(item_id)} appears more than once"))
        else:
            seen_ids.add(item_id)
        _check_choice(item.get("status"), V8, f"{where}.status", ITEM_STATUSES, problems)
        _check_timestamp(item.get("answered_at"), f"{where}.answered_at", problems)
        flag_bare_datetimes(item, where, problems, skip={f"{where}.answered_at"})
    irb = ethics.get("irb")
    if not isinstance(irb, dict):
        problems.append(Problem(V8, "ethics.irb", "must be a mapping with required and status"))
    else:
        required = irb.get("required")
        if not isinstance(required, bool):
            detail = "is missing" if required is None else f"{_q(required)} is not true or false"
            problems.append(Problem(V8, "ethics.irb.required", detail))
        _check_choice(irb.get("status"), V8, "ethics.irb.status", IRB_STATUSES, problems)
        _check_timestamp(irb.get("status_changed_at"), "ethics.irb.status_changed_at", problems)
        flag_bare_datetimes(irb, "ethics.irb", problems, skip={"ethics.irb.status_changed_at"})
    for key, value in ethics.items():
        if key not in ("items", "irb"):
            flag_bare_datetimes(value, f"ethics.{key}", problems)


def check_track(track, problems):
    """Apply V9 and V10 to a parsed TRACK Log block."""
    events = track.get("events")
    if not isinstance(events, list):
        problems.append(Problem(V9, "track.events", "must be a list (use [] when empty)"))
        events = []
    for index, event in enumerate(events):
        where = f"track.events[{index}]"
        if not isinstance(event, dict):
            problems.append(Problem(V9, where, "must be a mapping with ts and kind"))
            continue
        ts = event.get("ts")
        if ts is None:
            problems.append(Problem(V9, f"{where}.ts", "is missing"))
        _check_timestamp(ts, f"{where}.ts", problems)
        _check_choice(event.get("kind"), V9, f"{where}.kind", EVENT_KINDS, problems)
        flag_bare_datetimes(event, where, problems, skip={f"{where}.ts"})
    for key, value in track.items():
        if key != "events":
            flag_bare_datetimes(value, f"track.{key}", problems)


def in_reconfirmation_set(item):
    """True for roster items that must be reconfirmed after IRB approval."""
    return item.category in RECONFIRM_CATEGORIES or item.item_id in RECONFIRM_IDS


def _needs_action_reason(item):
    return (f"{item.item_id} {item.label}: NEEDS_ACTION "
            f"(category {item.category}, {item.category_name})")


def derive(ethics, roster):
    """Derive (ethics_status, reasons) from a valid Ethics Checklist Status block."""
    by_id = {item["id"]: item for item in ethics["items"]}
    missing = [item.item_id for item in roster if item.item_id not in by_id]
    unanswered = [item.item_id for item in roster
                  if item.item_id in by_id and by_id[item.item_id].get("answered_at") is None]
    unassessed = []
    if missing:
        unassessed.append("missing from items: " + ", ".join(missing))
    if unanswered:
        unassessed.append("not answered yet (answered_at is empty): " + ", ".join(unanswered))
    if unassessed:
        return "NOT_YET_ASSESSED", unassessed

    def status_of(item):
        return by_id[item.item_id]["status"]

    blocked = [item for item in roster if item.category <= 4 and status_of(item) == "NEEDS_ACTION"]
    if blocked:
        return "ETHICS_BLOCKED", [_needs_action_reason(item) for item in blocked]

    reasons = []
    irb = ethics["irb"]
    changed_at = irb.get("status_changed_at")
    if irb["required"]:
        if irb["status"] in ("SUBMITTED", "NOT_YET_SUBMITTED"):
            reasons.append(f"IRB approval required, status {irb['status']}")
        elif changed_at is None:
            reasons.append(f"IRB approval required, status {irb['status']} has no status_changed_at")
        elif irb["status"] == "APPROVED":
            approved = parse_timestamp(changed_at)
            stale = [item.item_id for item in roster
                     if in_reconfirmation_set(item) and status_of(item) == "PASS"
                     and parse_timestamp(by_id[item.item_id]["answered_at"]) < approved]
            if stale:
                reasons.append(f"not reconfirmed since IRB approval at {changed_at}: " + ", ".join(stale))
    reasons += [_needs_action_reason(item) for item in roster
                if item.category >= 5 and status_of(item) == "NEEDS_ACTION"]
    if reasons:
        return "ETHICS_PENDING", reasons
    return "READY", ["none"]


def check_artifact(text, roster):
    """Validate artifact text; for a valid artifact also derive its ethics_status."""
    problems = []
    split = split_frontmatter(_numbered_lines(text))
    if split is None:
        problems.append(Problem(V1, "frontmatter", "the file must start with a '---' line "
                                "and close the frontmatter with another '---' line"))
        return Result(problems, None, None, None, [])
    frontmatter_lines, body = split
    frontmatter, error = _parse_yaml("\n".join(line for _, line in frontmatter_lines), 2,
                                     "the frontmatter must be a mapping of fields")
    if error:
        problems.append(Problem(V2, "frontmatter", error))
    else:
        check_frontmatter(frontmatter, problems)
    sections, hidden = split_sections(body)
    headings = [section.heading for section in sections]
    for name in REQUIRED_SECTIONS:
        if name not in headings:
            detail = "section is missing"
            if name in hidden:
                detail += " (its heading on line %d is inside a code block opened on line %d)" % hidden[name]
            problems.append(Problem(V7, f"## {name}", detail))
    ethics = _section_block(sections, hidden, ETHICS_SECTION, V8, "items and irb", problems)
    if ethics is not None:
        check_ethics(ethics, roster, problems)
    track = _section_block(sections, hidden, TRACK_SECTION, V9, "events", problems)
    if track is not None:
        check_track(track, problems)
    if problems:
        return Result(problems, frontmatter, ethics, None, [])
    status, reasons = derive(ethics, roster)
    return Result(problems, frontmatter, ethics, status, reasons)


def format_result(path, result, roster):
    """Render the checker's plain-text report."""
    lines = ["study_state_check", f"file: {_show(path)}"]
    if not result.valid:
        lines += ["result: INVALID", "problems:"]
        lines += [f"  - [{problem.rule}] {problem.location}: {problem.detail}" for problem in result.problems]
        lines.append("ethics_status: not computed (artifact is invalid)")
    else:
        frontmatter, ethics, irb = result.frontmatter, result.ethics, result.ethics["irb"]
        answered = [item for item in ethics["items"] if item.get("answered_at") is not None]
        counts = Counter(item["status"] for item in answered)
        irb_line = f"irb: {'required' if irb['required'] else 'not required'}, {irb['status']}"
        if irb.get("status_changed_at") is not None:
            irb_line += f" since {irb['status_changed_at']}"
        if _present(irb.get("approval_reference")):
            irb_line += f" (ref {_show(irb['approval_reference'])})"
        lines += [
            "result: VALID",
            f"study: {_show(frontmatter['study_id'])} | revision {frontmatter['revision']}"
            f" | phase {frontmatter['current_phase']}",
            f"ethics_status: {result.status}",
            "reasons:",
        ]
        lines += [f"  - {reason}" for reason in result.reasons]
        lines += [
            f"checklist: {len(answered)}/{len(roster)} answered (PASS {counts['PASS']}, "
            f"NOT_APPLICABLE {counts['NOT_APPLICABLE']}, NEEDS_ACTION {counts['NEEDS_ACTION']})",
            irb_line,
        ]
    # No value from the artifact can add a line: every line is escaped here, whatever built it.
    return "\n".join(_oneline(line) for line in lines)


def main(argv=None):
    """Check one artifact; print the report and return the exit code."""
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 1:
            raise CannotRun("usage: python3 check_study_state.py <path-to-state.md>")
        if yaml is None:
            raise CannotRun(f"PyYAML is not installed for {sys.executable} "
                            "(python3 -m pip install pyyaml)")
        roster = load_roster()
        path = args[0]
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise CannotRun(f"{path} is not UTF-8 text") from None
        except OSError as err:
            raise CannotRun(f"cannot read {path}: {err.strerror or err}") from None
        try:
            result = check_artifact(text, roster)
            output = format_result(path, result, roster)
            # The report shows non-ASCII values as-is, which a platform default such as cp1252 cannot encode.
            sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
            print(output)
        except Exception as err:  # checker bugs and output failures must not look like an INVALID artifact
            raise CannotRun(f"internal error: {type(err).__name__}: {err}") from None
    except CannotRun as err:
        print(f"study_state_check: cannot run: {_oneline(str(err))}", file=sys.stderr)
        return 2
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
