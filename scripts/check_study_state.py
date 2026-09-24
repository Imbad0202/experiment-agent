#!/usr/bin/env python3
"""Validate a study state artifact and derive its ethics_status.

Usage:
    python3 scripts/check_study_state.py <path-to-state.md>
    python3 scripts/check_study_state.py --now    (prints the current time)

Exit codes: 0 = VALID or --now printed the time, 1 = INVALID, 2 = cannot run (reason on stderr).
Reads the artifact and references/study_state_protocol.md; writes nothing.
Rules: docs/specs/2026-09-24-study-state-checker-design.md
"""

import datetime
import decimal
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
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
SECTIONS = REQUIRED_SECTIONS + ("COLLECT Readiness",)  # the body's only headings, each written '## <name>'
CHECKED_SECTIONS = (ETHICS_SECTION, TRACK_SECTION)  # the sections whose yaml blocks the checker reads
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
LINE_BREAK_RE = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]")

# Markdown layout, read as CommonMark does wherever a difference could show a reader
# something other than what the checker reads.
LINE_END_RE = re.compile(r"\r\n|\r|\n")
# A frontmatter line that some reader takes as the end of the frontmatter: one starting "---" (gray-matter),
# three or more "-" alone after at most three spaces (markdown-it-front-matter), or "..." alone however
# indented (markdown-it-front-matter, and Jekyll with spaces after it).
FRONTMATTER_END_RE = re.compile(r"---.*| {0,3}-{3,}\s*|[ \t]*\.\.\.\s*")
FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
# A block quote marker, a footnote label (GitHub reads a footnote as a container), or a list marker
# with text after it.
CONTAINER_MARKER = r"(?:>|\[\^[^\]]+\]:|(?:[-+*]|[0-9]{1,9}[.)])(?=[ \t]+\S))[ \t]?"
# The markers where a reader takes them, for finding indented code by its columns.
CONTAINER_RE = re.compile(r" {0,3}" + CONTAINER_MARKER)
# The same markers after any indentation, as in a list nested in a list item.
ANY_CONTAINER_RE = re.compile(r"[ \t]*" + CONTAINER_MARKER)
# A heading line once its markers and indentation are removed, and a line that underlines the text above
# it into a heading once its indentation and quote markers are removed.
ATX_RE = re.compile(r"#{1,6}(?:[ \t]|$)")
UNDERLINE_RE = re.compile(r"(?:=+|-+)[ \t]*")
TAG_NAME = r"[A-Za-z][A-Za-z0-9-]*"
# A space or a tab: every reader takes it as a space between a tag's parts and never as part of an unquoted
# value, so the tag pattern matches each tag one way only and a long line takes linear time.
TAG_SPACE_CHARS = r" \t"
TAG_SPACE = f"[{TAG_SPACE_CHARS}]"
ATTRIBUTE = (rf"{TAG_SPACE}+[A-Za-z_:][A-Za-z0-9_.:-]*"
             rf"""(?:{TAG_SPACE}*={TAG_SPACE}*(?:[^{TAG_SPACE_CHARS}"'=<>`]+|'[^']*'|"[^"]*"))?""")
TAG_BODY = rf"{TAG_NAME}(?:{ATTRIBUTE})*{TAG_SPACE}*"  # a tag's name, attributes and spaces
# A tag, or `<!` or `<?`, which start a comment, a declaration, CDATA or a processing instruction.
HTML_RE = re.compile(rf"<{TAG_BODY}/?>|</{TAG_NAME}{TAG_SPACE}*>|<!|<\?")
# A tag still open at the end of a line: a reader can finish it on the next line, after any markers there.
OPEN_TAG_RE = re.compile(rf"""</?{TAG_BODY}(?:={TAG_SPACE}*(?:"[^"]*|'[^']*)?)?$""")
# Any other whitespace, such as a vertical tab, a form feed, U+001C to U+001F, U+00A0, U+3000 or U+FEFF: some
# readers take it as a space in a tag, some as part of an unquoted value, some as neither. After a '<' or '</'
# and a letter, any of it on the line counts as HTML, however the tag reads.
TAG_START_RE = re.compile(r"</?[A-Za-z]")
OTHER_SPACE_RE = re.compile(rf"(?!{TAG_SPACE})[\s\uFEFF]")
# The start of an HTML block, before its tag is complete. It counts anywhere on the line, so no list, quote
# or other container has to be worked out.
HTML_BLOCK_RE = re.compile(
    rf"<(?:script|pre|style|textarea)(?:{TAG_SPACE}|>|$)|</?(?:address|article|aside|base|basefont|"
    r"blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|"
    r"figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|link|main|menu|"
    r"menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|source|summary|table|tbody|td|"
    rf"tfoot|th|thead|title|tr|track|ul)(?:{TAG_SPACE}|/?>|$)", re.IGNORECASE)
HTML_DETAIL = "line %d has HTML, which can hide text from a reader; study state artifacts do not use HTML"
HEADINGS_ONLY = "the only headings are " + ", ".join(f"'## {name}'" for name in SECTIONS)
OTHER_HEADING = ("line %d makes a heading other than the four section headings; " + HEADINGS_ONLY
                 + " (use bold text for a label)")
UNDERLINED = ("line %d is a line of '-' or '=' right under text, which can make that text a heading; "
              + HEADINGS_ONLY + " (leave a blank line above a rule, and use bold text for a label)")
MISPLACED_FENCE = ("line %d starts a code block that is not at the first column; start ``` at the first "
                   "column, outside any list or quote")
# GitHub keeps a fence's length in one byte, so it ends a longer fence at the first later line of 255 or more;
# other readers read on past a line shorter than the fence.
MAX_FENCE_LENGTH = 255
LONG_FENCE = (f"line %d starts a code block with more than {MAX_FENCE_LENGTH} backticks or tildes, which "
              "readers end at different lines; start a code block with ```")
# markdown-it shows nothing below a list nested past its limit: ten lists with its CommonMark settings, fifty
# with its default ones. Each list takes at least two columns, so a line whose markers and indentation take
# this many columns is malformed, two lists short of the lower limit.
DEEP_COLUMN = 16
DEEP_TEXT = (f"line %d has list, quote or footnote markers and indentation {DEEP_COLUMN} or more columns "
             "wide; some readers stop showing the rest of a file at lists nested about that deep, so nest "
             "lists and quotes less deeply")
# VS Code's preview reads a line starting "$$" as a math block, which takes the lines below it up to one with
# "$$" in it, or to the end of the file.
MATH_BLOCK = ("line %d starts with '$$', which VS Code's preview reads as a math block that can take the "
              "lines below it; study state artifacts do not use math blocks")


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


@dataclass
class Section:
    heading: str  # None for the text before the first section
    line: int
    yaml_blocks: list  # (first content line, text) of each yaml or yml block
    open_fence: int = None  # line of a code fence still open at the end of the file
    html: int = None  # first line with HTML
    stray: str = None  # the first other heading, misplaced or overlong fence, deep line, or math block
    other_code: str = None  # where the first code other than a yaml block is


class Layout(NamedTuple):
    sections: list  # the text before the first section heading, then one Section per section heading
    hidden: dict  # heading of a '## ' line inside a code block -> (its line, the line that opened the block)


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


# Limits no artifact comes near: Python cannot read or print an integer of more than 4300 digits,
# and its stack runs out at a few hundred levels of YAML nesting.
MAX_NUMBER_LENGTH = 100
MAX_NESTING = 100
TOO_DEEP = f"found values nested more than {MAX_NESTING} levels deep, which study state artifacts do not use"
# YAML also ends a line at these characters and a Markdown reader does not, so the two would read
# different lines.
YAML_ONLY_LINE_BREAK_RE = re.compile(r"[\x85\u2028\u2029]")


def _string_loader():
    """A SafeLoader that leaves timestamps, decimal numbers and a lone "=" as strings and rejects
    tags, repeated keys, merge keys, overlong or malformed numbers and deep nesting."""
    class Loader(yaml.SafeLoader):
        depth = 0  # nesting of the node being composed

        def __init__(self, stream):
            super().__init__(stream)
            self.heights = {}  # each composed node: its levels of nesting, through aliases

        def compose_node(self, parent, index):
            # A tag such as !!timestamp or !!int builds a value that skips the checks that expect text,
            # or fails outside YAML's own errors.
            event = self.peek_event()
            if getattr(event, "tag", None) is not None:
                shown = event.tag.replace("tag:yaml.org,2002:", "!!")
                raise yaml.composer.ComposerError(
                    None, None, f"found the tag {_q(shown)}, which study state artifacts do not use",
                    event.start_mark)
            if self.depth == MAX_NESTING:
                raise yaml.composer.ComposerError(None, None, TOO_DEEP, event.start_mark)
            self.depth += 1
            try:
                node = super().compose_node(parent, index)
            finally:
                self.depth -= 1
            # An alias repeats a node without nesting in the text, so the node's height counts where the
            # alias sits. An alias inside the node it names finds no height yet: it nests without end.
            # Any other node is no deeper than its children, which were checked when they were composed.
            if isinstance(event, yaml.AliasEvent):
                height = self.heights.get(node)
                if height is None or self.depth + height > MAX_NESTING:
                    raise yaml.composer.ComposerError(None, None, TOO_DEEP, event.start_mark)
                return node
            if isinstance(node, yaml.MappingNode):
                children = [child for pair in node.value for child in pair]
            else:
                children = node.value if isinstance(node, yaml.SequenceNode) else []
            self.heights[node] = 1 + max((self.heights[child] for child in children), default=0)
            return node

        def fetch_directive(self):
            # A %YAML or %TAG line changes how the rest is read, and Python's int() takes time that grows with
            # the square of a long %YAML version number.
            raise yaml.scanner.ScannerError(
                None, None, "found a YAML directive (a line starting with %), which study state artifacts do "
                "not use", self.get_mark())

        def fetch_more_tokens(self):
            # Some text that YAML scans names a value Python cannot build, such as an escape past U+10FFFF.
            # That is the artifact's error; an error in the checker's own code still stops it (exit 2).
            try:
                super().fetch_more_tokens()
            except (ValueError, OverflowError):
                raise yaml.scanner.ScannerError(
                    None, None, "found a value that Python cannot read", self.get_mark()) from None

        def construct_yaml_int(self, node):
            if len(node.value) > MAX_NUMBER_LENGTH:
                raise yaml.constructor.ConstructorError(
                    None, None, f"found a number longer than {MAX_NUMBER_LENGTH} characters, which study "
                    "state artifacts do not use", node.start_mark)
            try:
                return super().construct_yaml_int(node)
            except ValueError:  # YAML 1.1 reads 0b_ and 0x_ as numbers, which then have no digits
                raise yaml.constructor.ConstructorError(
                    None, None, f"found the malformed number {_q(node.value)}", node.start_mark) from None

        def construct_mapping(self, node, deep=False):
            # PyYAML keeps the last of repeated keys; the value it drops could be the blocking one.
            # A merge (<<) can bring in a repeated key and can grow without limit.
            if isinstance(node, yaml.MappingNode):
                keys = set()
                for key_node, _ in node.value:
                    if key_node.tag == "tag:yaml.org,2002:merge":
                        raise yaml.constructor.ConstructorError(
                            None, None, "found a merge key (<<), which study state artifacts do not use",
                            key_node.start_mark)
                    if not isinstance(key_node, yaml.ScalarNode):
                        continue  # complex keys fail in the base class
                    key = self.construct_object(key_node)
                    if key in keys:
                        raise yaml.constructor.ConstructorError(
                            None, None, f"found duplicate key {_q(key)}", key_node.start_mark)
                    keys.add(key)
            return super().construct_mapping(node, deep=deep)

    Loader.add_constructor("tag:yaml.org,2002:int", Loader.construct_yaml_int)
    dropped = ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:float", "tag:yaml.org,2002:value")
    Loader.yaml_implicit_resolvers = {
        first: [(tag, regexp) for tag, regexp in resolvers if tag not in dropped]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return Loader


def load_yaml(text):
    """Parse YAML safely; timestamps stay strings and item IDs stay as written."""
    separator = YAML_ONLY_LINE_BREAK_RE.search(text)
    if separator:
        line = text.count("\n", 0, separator.start())
        raise yaml.MarkedYAMLError(
            None, None, "found the line separator U+%04X, which study state artifacts do not use"
            % ord(separator.group()), yaml.Mark("<artifact>", separator.start(), line, 0, None, None))
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
    """Split text into (line number, line) pairs at CRLF, CR or LF, as Markdown does."""
    return list(enumerate(LINE_END_RE.split(text), start=1))


def split_frontmatter(lines):
    """Return ((frontmatter lines, body lines), None), or (None, the problem) when a delimiter is missing,
    a byte order mark comes before it, or a line before the closing one could end the frontmatter for some
    reader, as "---" with whitespace after it does."""
    if lines and lines[0][1].startswith("\ufeff"):
        # markdown-it's front-matter plugins do not skip it, and then show the whole frontmatter as text.
        return None, ("the file starts with a byte order mark (U+FEFF), which some readers do not skip "
                      "before the frontmatter; save the file as UTF-8 without it")
    missing = ("the file must start with a line that is exactly '---' and close the frontmatter with another "
               "such line")
    if not lines or lines[0][1] != "---":
        return None, missing
    for index in range(1, len(lines)):
        number, text = lines[index]
        if text == "---":
            return (lines[1:index], lines[index + 1:]), None
        if FRONTMATTER_END_RE.fullmatch(text):
            return None, (f"line {number} could end the frontmatter for some readers; before the closing "
                          "'---', no line may start with '---' or hold only '-' characters or '...'")
    return None, missing


def _fence_opening(text):
    """Return (fence, info string) when the line opens a fenced code block."""
    match = FENCE_RE.fullmatch(text)
    if not match:
        return None
    fence, info = match.groups()
    if fence[0] == "`" and "`" in info:
        return None  # a backtick fence's info string cannot contain backticks
    return fence, info.strip(" \t")


def _fence_closes(text, fence):
    """True when the line closes the fence: a fence line of the same character, at least as long,
    with no info string."""
    closing = _fence_opening(text)
    return (closing is not None and not closing[1]
            and closing[0][0] == fence[0] and len(closing[0]) >= len(fence))


def _strip_containers(text, markers=CONTAINER_RE):
    """The line without the container markers (block quote, list, footnote) it starts with."""
    position = 0
    while True:
        match = markers.match(text, position)
        if not match:
            return text[position:]
        position = match.end()


def _has_html(text):
    """True when a line outside code blocks could show a reader HTML: a tag, `<!` or `<?`, or the start of an
    HTML block anywhere on it; a tag still open at its end; or a '<' or '</' and a letter followed on the line
    by whitespace other than a space or a tab. The line is read alone and as written, so no marker on it or
    on the next line can hide a tag."""
    if HTML_RE.search(text) or HTML_BLOCK_RE.search(text) or OPEN_TAG_RE.search(text):
        return True
    start = TAG_START_RE.search(text)
    return bool(start and OTHER_SPACE_RE.search(text, start.end()))


def split_sections(body):
    """Read the body's layout: its sections, their yaml blocks, other code, and whatever could show a
    reader something other than what the checker reads (HTML, a heading other than the four section
    headings, a code block not at the first column or with a fence over 255 characters, a line nested 16
    or more columns deep, a math block, a section heading inside a code block, an unclosed fence)."""
    sections, hidden = [Section(None, 0, [])], {}
    fence = fence_line = block = None
    after_text = False  # whether the line above is one that a line of - or = could underline
    for number, text in body:
        section = sections[-1]
        heading = text[3:].rstrip() if text.startswith("## ") else None
        if fence:
            if _fence_closes(text, fence):
                if block is not None:
                    section.yaml_blocks.append((fence_line + 1, "\n".join(block)))
                fence = block = None
                continue
            if block is not None:
                block.append(text)
            if heading is not None:
                hidden.setdefault(heading, (number, fence_line))
            continue
        starts_section = heading in SECTIONS
        opening = _fence_opening(text)
        # The line once its container markers and indentation are removed, however deep they go.
        content = _strip_containers(text, ANY_CONTAINER_RE).lstrip(" \t")
        misplaced = content != text and _fence_opening(content)  # indented, or in a container
        if misplaced:
            section.stray = section.stray or MISPLACED_FENCE % number
        if opening or starts_section:
            after_text = False
        if opening:
            fence, info = opening
            fence_line = number
            if len(fence) > MAX_FENCE_LENGTH:
                section.stray = section.stray or LONG_FENCE % number
            if re.split(r"[ \t]", info, maxsplit=1)[0].lower() in ("yaml", "yml"):
                block = []
            else:
                section.other_code = (section.other_code
                                      or f"the code block on line {number} is not a yaml block")
            continue
        if starts_section:
            sections.append(Section(heading, number, []))
            continue
        if not section.html and _has_html(text):
            section.html = number
        # A tab reaches the next multiple of 4 columns, for a reader too, so tabs go before the markers.
        expanded = text.expandtabs(4)
        stripped = _strip_containers(expanded)
        if stripped.strip(" \t") and not misplaced and stripped.startswith("    "):
            section.other_code = section.other_code or f"line {number} is indented, which makes it code"
        # The columns before the text, or up to the end of the markers on a line with only markers; a blank
        # line opens nothing.
        marked = expanded.rstrip(" ")
        depth = len(marked) - len(_strip_containers(marked, ANY_CONTAINER_RE).lstrip(" "))
        if marked and depth >= DEEP_COLUMN:
            section.stray = section.stray or DEEP_TEXT % number
        # A heading a reader could see. Lists and quotes are not worked out, so a line of - or = right under
        # any line that is not blank counts, even where a reader sees a rule that ends a list or quote.
        if content.startswith("$$"):
            section.stray = section.stray or MATH_BLOCK % number
        if ATX_RE.match(content):
            section.stray = section.stray or OTHER_HEADING % number
        elif after_text and UNDERLINE_RE.fullmatch(text.lstrip(" \t>")):
            section.stray = section.stray or UNDERLINED % number
        after_text = bool(text.strip(" \t"))
    if fence:
        sections[-1].open_fence = fence_line
    return Layout(sections, hidden)


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


def _string_leaves(value, path, seen, keys=()):
    """Yield (path, keys, text) for every string in value, visiting each container once. keys holds the
    keys and indexes that lead to the string; path shows them, and a key with a dot in it can make two
    paths look alike."""
    if isinstance(value, str):
        yield path, keys, value
    elif isinstance(value, (dict, list)) and id(value) not in seen:
        seen.add(id(value))  # YAML aliases can repeat one container many times
        if isinstance(value, dict):
            for key, child in value.items():
                yield from _string_leaves(child, f"{path}.{key}", seen, keys + (key,))
        else:
            for index, child in enumerate(value):
                yield from _string_leaves(child, f"{path}[{index}]", seen, keys + (index,))


def flag_bare_datetimes(value, path, problems, skip=()):
    """V10 for other fields: a string that is just a date and a time has no offset. skip holds the keys
    that lead to fields already checked as timestamps."""
    for where, keys, text in _string_leaves(value, path, set()):
        if keys not in skip and BARE_DATETIME_RE.fullmatch(text):
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
    flag_bare_datetimes(frontmatter, "frontmatter", problems,
                        skip={("created",), ("updated",), ("track_summary", "last_event_ts")})


def _section_block(layout, name, rule, keys, problems):
    """Parse the one yaml block of the named section; record why when that fails."""
    found = [section for section in layout.sections if section.heading == name]
    if not found:
        return None  # reported under V7
    section = found[0]
    if len(found) > 1:
        lines = ", ".join(str(copy.line) for copy in found)
        detail = f"section appears {len(found)} times (lines {lines}); it must appear once"
    elif name in layout.hidden:
        detail = ("another heading for this section on line %d is inside a code block opened on line %d; "
                  "the section must appear once" % layout.hidden[name])
    elif section.html:
        detail = HTML_DETAIL % section.html
    elif section.stray:
        detail = section.stray
    elif section.open_fence:
        detail = f"a code block opened on line {section.open_fence} is never closed"
    elif len(section.yaml_blocks) != 1:
        detail = f"section has {len(section.yaml_blocks) or 'no'} yaml blocks; it must have exactly one"
    elif section.other_code:
        detail = f"{section.other_code}; the section holds only text and its one yaml block"
    else:
        first_line, text = section.yaml_blocks[0]
        data, detail = _parse_yaml(text, first_line, f"the yaml block must be a mapping with {keys}")
        if detail is None:
            return data
    problems.append(Problem(rule, f"## {name}", detail))
    return None


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
        flag_bare_datetimes(item, where, problems, skip={("answered_at",)})
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
        flag_bare_datetimes(irb, "ethics.irb", problems, skip={("status_changed_at",)})
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
        flag_bare_datetimes(event, where, problems, skip={("ts",)})
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
                     and parse_timestamp(by_id[item.item_id]["answered_at"]) <= approved]
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
    split, error = split_frontmatter(_numbered_lines(text))
    if error:
        problems.append(Problem(V1, "frontmatter", error))
        return Result(problems, None, None, None, [])
    frontmatter_lines, body = split
    frontmatter, error = _parse_yaml("\n".join(line for _, line in frontmatter_lines), 2,
                                     "the frontmatter must be a mapping of fields")
    if error:
        problems.append(Problem(V2, "frontmatter", error))
    else:
        check_frontmatter(frontmatter, problems)
    layout = split_sections(body)
    headings = [section.heading for section in layout.sections]
    for name in REQUIRED_SECTIONS:
        if name not in headings:
            detail = "section is missing"
            if name in layout.hidden:
                detail += (" (its heading on line %d is inside a code block opened on line %d)"
                           % layout.hidden[name])
            problems.append(Problem(V7, f"## {name}", detail))
    for section in layout.sections:
        if section.heading not in CHECKED_SECTIONS:
            # HTML, a misplaced or overlong code fence, a line nested too deep, or a math block can hide a
            # section, and another heading can pass for one; the checked sections report these under their own
            # rule.
            if section.html:
                problems.append(Problem(V7, "body", HTML_DETAIL % section.html))
            if section.stray:
                problems.append(Problem(V7, "body", section.stray))
    ethics = _section_block(layout, ETHICS_SECTION, V8, "items and irb", problems)
    if ethics is not None:
        check_ethics(ethics, roster, problems)
    track = _section_block(layout, TRACK_SECTION, V9, "events", problems)
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
    """Check one artifact, or with --now print the current time; return the exit code."""
    args = sys.argv[1:] if argv is None else argv
    if args == ["--now"]:
        # The agent records every current time from here, so recorded times compare in the order they
        # happened.
        print(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
        return 0
    try:
        if len(args) != 1:
            raise CannotRun("usage: python3 check_study_state.py <path-to-state.md>, "
                            "or --now for the current time")
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
