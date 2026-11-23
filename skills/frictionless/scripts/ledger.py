#!/usr/bin/env python3
"""Selenite friction ledger: one JSON line per friction event.

  ledger.py add <kind> <key> [--note TEXT] [--agent NAME]
  ledger.py summary [--days N]
  ledger.py state-dir          print the first state folder that accepts a write

kind: gate | calm | audit | cleanse | approval | blocked | miss | fp | fix | reopen
key:  a short stable slug for the friction (e.g. gh-login, npm-otp).
Keys and notes are redacted when written (emails, IPs, tokens, secrets, the
home path) and truncated: notes to 200 characters. A key longer than 80 characters
is cut to 71 and given a short hash, so two long keys never merge, and the
returned row says truncated: true.

Where state lives: $SELENITE_STATE, when set, is the only folder read or written
(so one seat on a shared host never reads another's friction). Otherwise
$XDG_STATE_HOME/selenite, then $HERMES_HOME/plugin-data/selenite, then
~/.local/state/selenite. Under XDG, each active Hermes home gets its own
by-home/<hash> folder. An agent seat normally has a read-only home and a
writable Hermes home, so the third choice is what keeps it working there. Every
write tries each folder in that order and gives up quietly instead of failing
the caller.

A user-wide fallback (XDG or ~/.local/state) is shared by every Hermes home on
the machine, so when it is only a fallback Selenite keeps its state in a
subfolder named for the preferred folder (by-home/<hash>). One home's gates,
fixes and reports never show up in, or get cleared from, another home.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    from hermes_constants import get_hermes_home, get_hermes_home_override
except ImportError:  # Standalone skill scripts do not need Hermes installed.
    get_hermes_home = get_hermes_home_override = None

if __package__:
    from . import pane
else:
    # Python -I omits the script directory; add this trusted sibling directory for pane.py.
    _SCRIPT_DIR = str(Path(__file__).resolve().parent)
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)
    import pane


def _active_hermes_home() -> Path | None:
    """Return the task's Hermes home when the host exposes its profile context."""
    active_override = get_hermes_home_override() if get_hermes_home_override else None
    if get_hermes_home and (os.environ.get("HERMES_HOME") or active_override):
        return Path(get_hermes_home()).expanduser()
    hermes = os.environ.get("HERMES_HOME")
    return Path(hermes).expanduser() if hermes else None


def _home_tag(home: Path | None = None) -> str:
    """A short, stable name for this home's state subfolder, without storing its path."""
    home = preferred_state() if home is None else home
    return hashlib.sha256(os.path.abspath(os.fspath(home)).encode()).hexdigest()[:12]


def _state_from_env() -> Path:
    """The folder Selenite prefers for this task, resolving the active Hermes profile."""
    explicit = os.environ.get("SELENITE_STATE")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        state = Path(xdg).expanduser() / "selenite"
        hermes = _active_hermes_home()
        return state / "by-home" / _home_tag(hermes) if hermes else state
    hermes = _active_hermes_home()
    if hermes:
        return hermes / "plugin-data/selenite"
    return Path.home() / ".local/state/selenite"


_INITIAL_STATE = _state_from_env()
STATE = _INITIAL_STATE  # compatibility handle; ledger operations resolve the path live


def preferred_state() -> Path:
    """The active task's preferred state folder, with support for callers overriding ``STATE``."""
    if STATE != _INITIAL_STATE:
        return STATE
    return _state_from_env()


def state_dirs() -> list[Path]:
    """Every folder Selenite may keep state in, most preferred first.

    The list exists because an agent seat is the product's normal home and its
    home folder is read-only: the preference falls through to a folder that
    takes the write instead of a traceback.
    """
    preferred = preferred_state()
    if _explicit(preferred):
        return [preferred]  # explicit state is the only search target
    xdg = os.environ.get("XDG_STATE_HOME")
    hermes = _active_hermes_home()
    shared = [Path(xdg).expanduser() / "selenite" if xdg else None, Path.home() / ".local/state/selenite"]
    own = hermes / "plugin-data/selenite" if hermes else None
    out = [preferred]
    for extra in (shared[0], own, shared[1]):
        if extra is None or extra == preferred:
            continue
        if extra == shared[0] and preferred.is_relative_to(extra):
            continue  # do not fall back from this home's XDG folder to the shared root
        if extra in shared:  # user-wide: keep this home's fallback state apart from every other home's
            extra = extra / "by-home" / _home_tag(preferred)
        if extra not in out:
            out.append(extra)
    return out


def _explicit(state: Path | None = None) -> bool:
    """True when SELENITE_STATE names the folder in use. Isolation follows the folder actually in use,
    so code that points STATE elsewhere gets the normal fallback list."""
    explicit = os.environ.get("SELENITE_STATE")
    in_use = preferred_state() if state is None else state
    return bool(explicit) and Path(explicit).expanduser() == in_use


def write_target() -> Path:
    """The folder the next write goes to, without creating anything: the first that exists and is
    writable, or whose nearest existing parent is. Falls back to the preferred folder when none would take it."""
    for state in state_dirs():
        probe = state
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        if probe.is_dir() and os.access(probe, os.W_OK):
            return state
    return preferred_state()


def writable_state() -> Path | None:
    """The first state folder that accepts a write, or None when all are read-only."""
    for state in state_dirs():
        try:
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(state, os.W_OK):
            return state
    return None


def newest(pattern: str) -> list[Path]:
    """Files matching ``pattern`` in every state folder, newest first. A write that fell through to a
    fallback folder is still found by every reader."""
    found: list[tuple[float, Path]] = []
    for state in state_dirs():
        try:
            for f in state.glob(pattern):
                try:
                    found.append((f.stat().st_mtime, f))
                except OSError:
                    continue
        except OSError:
            continue
    return [f for _, f in sorted(found, key=lambda t: t[0], reverse=True)]


BLOCKED_DAYS = 90  # how long a blocked-card row keeps its badge: one window for hooks and dashboard
LEDGER = STATE / "ledger.jsonl"
ROTATED = STATE / "ledger.1.jsonl"
LOCK_TIMEOUT_S = 3.0  # longest a writer waits for the ledger lock (TimeoutError is an OSError: add() moves on)
ROTATE_BYTES = 4 * 1024 * 1024  # one rotated file is kept; older history is dropped
KINDS = {"gate", "calm", "audit", "cleanse", "approval", "blocked", "miss", "fp", "fix", "reopen"}
APPROVAL_KEY = 71  # approval keys are cut here, so "approval:" + key fits the 80-character key limit


def _redact_card(match: re.Match[str]) -> str:
    digits = [int(d) for d in match.group() if d.isdigit()]
    checksum = 0
    for i, digit in enumerate(digits):
        if (len(digits) - i) % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return "<card>" if checksum % 10 == 0 else match.group()

# One shell command's arguments: blanks or a backslash-continued newline between them. The
# scan stops at an unescaped newline or a shell separator and covers at most 64 arguments.
_CMD_SEP = r"(?:[ \t]|\\\r?\n)+"
_CMD_ARGS = r"(?:" + _CMD_SEP + r"[^\s;|&]+){0,64}?" + _CMD_SEP
_SHELL_VALUE = r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|\S+)"
_CURL_COOKIE = re.compile(r"(?i)(\bcurl\b" + _CMD_ARGS + r"(?:-H|--header)" + _CMD_SEP + r")"
                         r"(['\"])(cookie\s*:\s*)[^'\"]*\2")
_CURL_COOKIE_ARG = re.compile(
    r"(?i)(\bcurl\b" + _CMD_ARGS + r"(?:--cookie|-[A-Za-z]*b)(?:" + _CMD_SEP + r"|=)?)(?:"
    r'(?P<double_quote>")(?=[^"\r\n]*=)[^"\r\n]*(?P=double_quote)|'
    r"(?P<single_quote>')(?=[^'\r\n]*=)[^'\r\n]*(?P=single_quote)|"
    r"(?=[^\s;|&]*=)[^\s;|&]+)"
)
_CURL_USER = re.compile(r"(?i)(\bcurl\b" + _CMD_ARGS + r"(?:--proxy-user|--user|-[A-Za-z]*u)(?:" + _CMD_SEP + r"|=)?)"
                        + _SHELL_VALUE)
_ROOTPW_PLAINTEXT = re.compile(r"(?i)(\brootpw\s+--plaintext\s+)" + _SHELL_VALUE)


def _quoted_secret(match: re.Match[str]) -> str:
    quote = match.group("double_quote") or match.group("single_quote") or ""
    return f"{quote}<secret>{quote}"


def _redact_authorization(match: re.Match[str]) -> str:
    return match.group(1) + match.group(2) + match.group(3) + _quoted_secret(match)


def _redact_curl_cookie_arg(match: re.Match[str]) -> str:
    return match.group(1) + _quoted_secret(match)


def _redact_key_value(match: re.Match[str]) -> str:
    return ((match.group("flag") or "") + match.group("key") + match.group("key_quote")
            + match.group("sep") + _quoted_secret(match))


_SECRET_KEY = (
    r"(?:[\w-]*(?:password|passphrase|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|credentials?|session[_-]?id|oauth|auth(?:key|code|[-_](?:key|code))?|"
    r"basic[-_]?auth|authorization|authentication)(?:s|[_-]?v?\d+)?|"
    r"[\w-]*(?:cookies?|cookies?[_-](?:jar|list|data)|cookie[_-]?(?:jar|list|data))|"
    r"[\w-]*(?:pass|pw)|(?:[\w-]+[-_])?key)"
)
_YAML_SECRET_NAME = r"(?:" + _SECRET_KEY + r"|[\w-]*(?:signature|cert))"


def _is_secret_name(name: str, *, allow_pass: bool = False) -> bool:
    name = name.strip().strip("\"'")
    credential_suffix = re.compile(
        r"(?i)(?:password|passphrase|passwd|pwd|pass|pw|secrets?|tokens?|"
        r"(?:api|access|private)[_-]?key|credentials?|cookies?|sessionid|oauth|"
        r"auth(?:key|code|[-_](?:key|code))?|basic[-_]?auth|authorization|authentication|signature|cert|key)$"
    )
    if not credential_suffix.search(name):
        return False
    if re.fullmatch(r"(?i)(?:num|total|min|max)[_-]?tokens?", name):
        return False
    return allow_pass or not re.search(r"(?i)(?:pass|pw)$", name)


_CREDENTIAL_CONTAINER = re.compile(
    r"(?i)(?<![\w-])(?P<prefix>[\"']?(?!(?:bypass|compass|encompass|surpass|overpass|underpass|trespass|max[_-]?tokens?)[\"']?\s*[=:])"
    + _SECRET_KEY + r"[\"']?\s*[=:]\s*)"
    r"(?P<open>[\[{(])"
)


def _container_end(text: str, start: int, *, line_bound: bool = True) -> tuple[int, bool]:
    """Return the end and closure state of a nested container."""
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack = [pairs[text[start]]]
    quote = ""
    escaped = False
    limit = text.find("\n", start) if line_bound else -1
    if limit < 0:
        limit = len(text)
    for pos in range(start + 1, limit):
        char = text[pos]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ("'", '\"') and text[pos - 1] in ":,[{( \t":
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif char in ("}", "]", ")"):
            if char != stack[-1]:
                return limit, False
            stack.pop()
            if not stack:
                return pos + 1, True
    return limit, False


def _redact_containers(text: str) -> str:
    """Replace complete recognized credential containers, including arbitrary nested leaves."""
    out = []
    cursor = 0
    for match in _CREDENTIAL_CONTAINER.finditer(text):
        if match.start() < cursor:
            continue
        open_pos = match.start("open")
        end, closed = _container_end(text, open_pos, line_bound=False)
        if not closed:
            end, closed = _container_end(text, open_pos, line_bound=True)
        if closed and not text[open_pos + 1:end - 1].strip():
            continue
        linked = False
        if closed and text[open_pos] == "[" and text[end:end + 1] == "(":
            link_end, link_closed = _container_end(text, end, line_bound=True)
            if link_closed:
                end = link_end
                linked = True
            else:
                end, closed = link_end, False
        if closed and text[open_pos] in "([" and not linked:
            inner = text[open_pos + 1:end - 1]
            simple = not any(c in inner for c in "\"',")
            if simple and not _contains_secret_token(inner):
                line_end = text.find("\n", end)
                if line_end < 0:
                    line_end = len(text)
                tail = text[end:line_end]
                secret_tail = next(
                    (m for m in re.finditer(r"[^\s,;|&]+", tail) if _looks_like_secret(m.group())),
                    None,
                )
                if secret_tail:
                    out.append(text[cursor:end] + tail[:secret_tail.start()] + "<secret>")
                    cursor = line_end
                continue
        if closed:
            while True:
                next_container = re.match(r"\s*,?\s*([\[{(])", text[end:])
                if not next_container:
                    break
                next_pos = end + next_container.end() - 1
                next_end, next_closed = _container_end(text, next_pos)
                if not next_closed:
                    end, closed = next_end, False
                    break
                end = next_end
            line_end = text.find("\n", end)
            if line_end < 0:
                line_end = len(text)
            tail = text[end:line_end]
            if any(_looks_like_secret(token) for token in re.findall(r"[^\s,;|&]+", tail)):
                end, closed = line_end, False
        out.append(text[cursor:match.start()])
        out.append(match.group("prefix") + '"<secret>"')
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_YAML_SECRET_BLOCK = re.compile(
    r"(?i)^(?P<indent>[ \t]*)(?P<list>-[ \t]+)?(?P<prefix>(?!(?:num|total|min|max)[_-]?tokens?[\"']?\s*:)(?P<key_quote>[\"']?)" + _YAML_SECRET_NAME
    + r"(?P=key_quote)\s*:\s*)"
    r"(?P<header>[|>])(?P<mods>[1-9+-]*)(?:[ \t]+#.*)?[ \t]*(?:\r?\n)?$"
)


def _redact_yaml_blocks(text: str) -> str:
    """Replace secret YAML block scalars, including blank continuation lines."""
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _YAML_SECRET_BLOCK.match(line.rstrip("\r\n"))
        if not match:
            out.append(line)
            i += 1
            continue
        parent_indent = len(match.group("indent"))
        indent_match = re.search(r"[1-9]", match.group("mods"))
        content_indent = parent_indent + int(indent_match.group()) if indent_match else None
        j = i + 1
        while j < len(lines):
            body = lines[j].rstrip("\r\n")
            if not body.strip():
                j += 1
                continue
            indent = len(body) - len(body.lstrip(" \t"))
            if content_indent is None:
                if indent <= parent_indent and re.match(r"[ \t]*[\w-]+\s*:", body):
                    break
                content_indent = indent
            elif indent <= parent_indent and re.match(r"[ \t]*[\w-]+\s*:", body):
                break
            if indent < content_indent:
                break
            j += 1
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        out.append(match.group("indent") + (match.group("list") or "") + match.group("prefix") + "<secret>" + newline)
        i = j
    return "".join(out)


def _redact_yaml_nested_values(text: str) -> str:
    """Replace indented YAML values that follow a secret key on their own line."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _YAML_SECRET_LINE.match(line.rstrip("\r\n"))
        value = match.group("value").strip() if match else ""
        if not match or (value and not value.startswith("#")):
            out.append(line)
            i += 1
            continue
        parent_indent = len(match.group("indent"))
        j = i + 1
        found_value = False
        while j < len(lines):
            body = lines[j].rstrip("\r\n")
            if not body.strip() or body.lstrip().startswith("#"):
                j += 1
                continue
            indent = len(body) - len(body.lstrip(" \t"))
            sequence_value = bool(re.match(r"[ \t]*-[ \t]+", body)) and indent >= parent_indent
            mapping = bool(re.match(r"[ \t]*[\w\"']+\s*:", body))
            if indent <= parent_indent and mapping:
                break
            if indent <= parent_indent and j != i + 1 and not sequence_value:
                break
            found_value = True
            j += 1
        if not found_value:
            out.append(line)
            i += 1
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        out.append(line[:match.start("value")] + "<secret>" + newline)
        i = j
    return "".join(out)


_SECRET_NAME_FIELD = re.compile(
    r"(?i)(?<![\w-])[\"']?(?:name|key)[\"']?\s*[:=]\s*[\"']?(?P<name>(?:" + _SECRET_KEY + r"|[\w-]*signature))[\"']?(?![\w-])"
)
_VALUE_FIELD = re.compile(r"(?i)(?<![\w-])[\"']?value[\"']?\s*[:=]\s*")
_YAML_NAME_FIELD = re.compile(r"(?im)^[ \t]*(?:-[ \t]*)?[\"']?(?:name|key)[\"']?\s*:")
_YAML_VALUE_FIELD = re.compile(r"(?im)^[ \t]*(?:-[ \t]*)?[\"']?value[\"']?\s*:")
_YAML_SECRET_LINE = re.compile(
    r"(?i)^(?P<indent>[ \t]*)(?P<list>-[ \t]+)?(?P<key_quote>[\"']?)(?P<key>" + _YAML_SECRET_NAME
    + r")(?P=key_quote)\s*:\s*(?P<value>.*?)(?P<newline>\r?\n)?$"
)


def _field_value_span(text: str, start: int, *, block_scalars: bool = True) -> tuple[int, int]:
    """Locate one scalar/container value, including a YAML block or a closed multiline quote."""
    pos = start
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    line_end = text.find("\n", pos)
    if line_end < 0:
        line_end = len(text)
    if pos >= line_end or text[pos] == "#":
        if not block_scalars:
            return pos, pos
        next_line = line_end + 1
        while next_line < len(text):
            end = text.find("\n", next_line)
            if end < 0:
                end = len(text)
            body = text[next_line:end].rstrip("\r")
            if not body.strip():
                next_line = end + 1
                continue
            if len(body) - len(body.lstrip(" \t")) <= 0:
                break
            return pos, end
        return pos, pos
    if block_scalars and text[pos] in "|>" and (pos + 1 == line_end or text[pos + 1] in "+-0123456789 #\t"):
        line_start = text.rfind("\n", 0, pos) + 1
        line_prefix = text[line_start:pos]
        indent = len(line_prefix) - len(line_prefix.lstrip(" \t"))
        end = line_end
        cursor = line_end + 1
        while cursor < len(text):
            next_end = text.find("\n", cursor)
            if next_end < 0:
                next_end = len(text)
            body = text[cursor:next_end].rstrip("\r")
            if body.strip() and len(body) - len(body.lstrip(" \t")) <= indent:
                break
            end = next_end
            cursor = next_end + 1
        return pos, end
    if text[pos] in "\"'":
        quote = text[pos]
        escaped = False
        cursor = pos + 1
        while cursor < len(text):
            char = text[cursor]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                return pos, cursor + 1
            elif char == "\n" and not block_scalars:
                return pos, line_end
            cursor += 1
        return pos, line_end
    if text[pos] in "{[(":
        end, closed = _container_end(text, pos, line_bound=False)
        return pos, end if closed else line_end
    end = pos
    while end < line_end:
        if text[end] == "#" and (end == pos or text[end - 1].isspace()):
            break
        if text[end].isspace():
            break
        end += 1
    return pos, end


def _replace_value(text: str, start: int, *, block_scalars: bool = True) -> str:
    value_start, value_end = _field_value_span(text, start, block_scalars=block_scalars)
    if value_start == value_end:
        return text
    return text[:value_start] + "<secret>" + text[value_end:]


def _redact_k8s_pairs(text: str) -> str:
    """Redact values paired with a secret-bearing name in one YAML item or inline object."""
    replacements: list[tuple[int, int, str]] = []
    lines = text.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    item_starts = []
    for i, line in enumerate(lines):
        match = re.match(r"^(?P<indent>[ \t]*)-[ \t]+", line)
        if match:
            item_starts.append((i, len(match.group("indent"))))
    groups: list[tuple[int, int]] = []
    for start_index, indent in item_starts:
        end_index = len(lines)
        for next_index, next_indent in item_starts:
            if next_index > start_index and next_indent <= indent:
                end_index = next_index
                break
        groups.append((start_index, end_index))
    if not item_starts:
        groups.append((0, len(lines)))

    for start_index, end_index in groups:
        begin = offsets[start_index] if start_index < len(offsets) else 0
        finish = offsets[end_index] if end_index < len(offsets) else len(text)
        group = text[begin:finish]
        yaml_pair = _YAML_NAME_FIELD.search(group) and _YAML_VALUE_FIELD.search(group)
        inline_assignments = any(
            _SECRET_NAME_FIELD.search(line) and _VALUE_FIELD.search(line) and not re.search(r"[{}\[\]]", line)
            for line in group.splitlines()
        )
        if not yaml_pair and not inline_assignments:
            continue
        names = list(_SECRET_NAME_FIELD.finditer(group))
        values = list(_VALUE_FIELD.finditer(group))
        if not names or not values:
            continue
        if not any(_is_secret_name(m.group("name"), allow_pass=True) for m in names):
            continue
        for field in values:
            value_start, value_end = _field_value_span(group, field.end())
            line_start = group.rfind("\n", 0, field.start()) + 1
            line_end = group.find("\n", field.end())
            if line_end < 0:
                line_end = len(group)
            field_indent = len(group[line_start:field.start()])
            if value_start < len(group) and group[value_start] in "\"'":
                quote = group[value_start]
                first_line = group[value_start + 1:line_end]
                first_line_closed = re.search(r"(?<!\\)" + re.escape(quote), first_line)
                if not first_line_closed and value_end > line_end:
                    content = group[value_start + 1:value_end - 1]
                    if not _contains_secret_token(content):
                        value_end = line_end
                if not first_line_closed and value_end == line_end:
                    next_start = line_end + 1
                    while next_start < len(group):
                        next_end = group.find("\n", next_start)
                        if next_end < 0:
                            next_end = len(group)
                        body = group[next_start:next_end].rstrip("\r")
                        indent = len(body) - len(body.lstrip(" \t"))
                        if re.match(r"[ \t]*(?:-[ \t]+)?[\"']?[\w-]+[\"']?[ \t]*:", body) and indent <= field_indent:
                            break
                        for token in re.finditer(r"[^\s,;|&]+", body):
                            if _looks_like_secret(token.group()):
                                replacements.append((begin + next_start + token.start(), begin + next_start + token.end(), "<secret>"))
                        next_start = next_end + 1
            raw_start = value_start
            while raw_start < line_end and group[raw_start] in " \t":
                raw_start += 1
            if (value_start < value_end and _YAML_VALUE_FIELD.match(group[line_start:line_end])
                    and group[raw_start] not in "\"'|>{[(" and group[raw_start] != "#"):
                comment = re.search(r"\s+#", group[raw_start:line_end])
                value_end = raw_start + comment.start() if comment else line_end
            if value_start < value_end:
                quote = group[value_start] if group[value_start] in "\"'" else ""
                replacement = quote + "<secret>" + quote if quote else "<secret>"
                replacements.append((begin + value_start, begin + value_end, replacement))

    # Multiline JSON and inline maps may not be represented as separate YAML lines.
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        end, closed = _container_end(text, start, line_bound=False)
        if not closed:
            continue
        body = text[start:end]
        names = list(_SECRET_NAME_FIELD.finditer(body))
        values = list(_VALUE_FIELD.finditer(body))
        if not names or not values or not any(_is_secret_name(m.group("name"), allow_pass=True) for m in names):
            continue
        for field in values:
            value_start, value_end = _field_value_span(body, field.end())
            if value_start < value_end:
                quote = body[value_start] if body[value_start] in "\"'" else ""
                replacement = quote + "<secret>" + quote if quote else "<secret>"
                replacements.append((start + value_start, start + value_end, replacement))

    for start, end, replacement in sorted(set(replacements), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _redact_yaml_multiline_values(text: str) -> str:
    """Redact closed multiline quoted values on a YAML key line; malformed quotes stop at EOL."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _YAML_SECRET_LINE.match(line.rstrip("\r\n"))
        if not match or not match.group("value").startswith(("\"", "'")):
            out.append(line)
            i += 1
            continue
        value_start = line.index(match.group("value"))
        quote = match.group("value")[0]
        parent_indent = len(match.group("indent"))
        escaped = False
        close_line = i
        close_col = -1
        closed = False
        for j in range(i, len(lines)):
            if j > i and lines[j].strip():
                indent = len(lines[j]) - len(lines[j].lstrip(" \t"))
                if indent <= parent_indent:
                    body = lines[j].strip()
                    folded_line = bool(re.fullmatch(r"[a-z0-9]+(?:[ \t]+[a-z0-9]+){0,2}", body))
                    if not _contains_secret_token(body) and not folded_line:
                        break
            start_col = value_start + 1 if j == i else 0
            for col in range(start_col, len(lines[j])):
                char = lines[j][col]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    close_line = j
                    close_col = col
                    closed = True
                    break
            if closed:
                break
        if closed:
            replacement = quote + "<secret>" + quote
            if close_line == i:
                out.append(line)
                i += 1
                continue
            out.append(line[:value_start] + replacement + lines[close_line][close_col + 1:])
            i = close_line + 1
        else:
            newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            out.append(line[:value_start] + quote + "<secret>" + quote + newline)
            i += 1
    return "".join(out)


def _looks_like_secret(value: str) -> bool:
    """A prose value is secret-shaped when it is opaque, mixed-case, or has token punctuation."""
    value = value.strip().strip("\"'`$.,;:()[]{}")
    if not value or value.startswith(("-", "/", "./", "../", "~/")):
        return False
    if re.search(r"\s", value):
        return False
    if re.fullmatch(r"\d+[A-Z][a-z]+", value):
        return False
    if re.fullmatch(r"(?i)(?:true|false|yes|no|ok|done|started|pending|n/?a|passed|success|successful|required|missing|not|valid|revoked|reset|rotated|expired|wrong|unknown|unavailable|false)", value):
        return False
    if value.isdigit() or re.fullmatch(r"\d+\s+of\s+\d+\s+checks?", value, re.IGNORECASE):
        return False
    if re.fullmatch(r"[A-Z]", value):
        return True
    if re.search(r"[0-9]", value) and re.search(r"[A-Za-z]", value):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_-]{7,}", value) and re.search(r"[_-]|[0-9]", value):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9]{24,}", value))


def _contains_secret_token(value: str) -> bool:
    return any(_looks_like_secret(part) for part in value.split())


def _mask_tail_secrets(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group()
        if not _looks_like_secret(raw):
            return raw
        if raw.startswith('"') and raw.endswith('"'):
            return '"<secret>"'
        if raw.startswith("'") and raw.endswith("'"):
            return "'<secret>'"
        return "<secret>"

    return re.sub(r"[^\s,;|&]+", replace, value)


_CREDENTIAL_WORD = r"(?:password|passphrase|passwd|pwd|pass|pw|secrets?|tokens?|(?:api|access|private)[ _-]+key)"
_ASSIGNMENT_KEY = r"(?:" + _SECRET_KEY + r"|(?:api|access|private)[ _-]+key)"
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?P<key_quote>[\"']?)(?P<key>(?!(?:bypass|compass|encompass|surpass|overpass|underpass|trespass)(?![\w-]))"
    + _ASSIGNMENT_KEY
    + r")(?P=key_quote)(?P<sep>\s*[=:]\s*)(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|"
    r"'(?:\\.|[^'\\\r\n])*'|\"[^\r\n]*|'[^\r\n]*|[^\s,;|&]+)"
)
_TRAILING_CREDENTIAL_KEY = r"(?:[\w-]*(?:password|passphrase|passwd|pwd|pass|pw|tokens?)|(?:api|access|private)[ _-]+key)"
_CREDENTIAL_TRAILING = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])(?![\"']?(?:proxy-)?authorization[\"']?\s*[=:])[\"']?"
    + _TRAILING_CREDENTIAL_KEY + r"[\"']?\s*[=:]\s*)"
    r"(?P<value>[^\r\n]*)"
)
_ASSIGNMENT_STATUS = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])[\"']?(?!(?:bypass|compass|encompass|surpass|overpass|underpass|trespass)(?![\w-]))"
    + _ASSIGNMENT_KEY
    + r"[\"']?\s*[=:]\s*)(?P<status>is|was|now)[ \t]+(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|"
    r"'(?:\\.|[^'\\\r\n])*'|[^\s,;|&]+)"
)
_PROSE_CREDENTIAL = re.compile(
    r"(?i)(?<![\w-])(?P<key>" + _CREDENTIAL_WORD + r")\b"
    r"(?P<qualifier>(?:[ \t]*\([^\r\n)]*\))?)"
    r"(?![ \t]*[:=])"
    r"(?P<phrase>(?:(?:[ \t]+[A-Za-z][A-Za-z'-]*)|[ \t]*[,;:]){0,8}[ \t]*(?:[=:][ \t]*|[ \t]+|\r?\n[ \t]*))"
    r"(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|\"[^\r\n]*|'[^\r\n]*|[^\s,;|&]+)"
)
_CREDENTIAL_STATUS_TAIL = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])(?P<key>" + _CREDENTIAL_WORD + r"|[\w-]*signature)\b"
    r"(?:[ \t]*[:=])?[ \t]+(?:(?:is|was|now)[ \t]+)?"
    r"(?:not(?:-[ \t]*|[ \t]+)|(?:wrong|required|missing|expired|valid|revoked|reset|rotated|unknown|unavailable)[.,;:]?[ \t]+))"
    r"(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|[^\s,;|&]+)"
)
_CREDENTIAL_EXPRESSION = re.compile(
    r"(?im)(?P<prefix>(?<![\w-])[\"']?(?:" + _SECRET_KEY + r")[\"']?\s*[=:]\s*)"
    r"(?P<value>[^\r\n]*(?:\b(?:getenv|environ|HTTPBasicAuth)\b|\bor\b|\+)[^\r\n]*)"
)
_OAUTH_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>(?<![\w-])[\w-]*oauth\s*[=:]\s*)(?P<api>(?:api[ _-]?key\s+))?"
    r"(?P<scheme>(?:bearer|basic|token)[ \t]+)?"
    r"(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|[^\s,;|&]+)"
)
_SHORT_PASS = re.compile(
    r"(?i)(?<![\w-])(?P<flag>-{1,2})?(?P<key>(?!(?:bypass|compass|encompass|surpass|overpass|underpass|trespass)(?![\w-]))"
    r"(?:[\w-]*(?:password|passphrase|passwd|pwd|pass|pw)|p))(?P<quote>[\"']?)(?P<sep>[ \t]+)"
    r"(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|\"[^\r\n]*|'[^\r\n]*|[^\s,;|&]+)"
)
_HAWK_AUTH = re.compile(r"(?im)(?P<prefix>\b(?:proxy-)?authorization[\"']?\s*[=:]\s*)Hawk\b[^\r\n]*")
_HTTP_SIGNATURE = re.compile(
    r"(?im)(?P<prefix>(?<![\w-])(?:x-hub-signature(?:-\d+)?|stripe-signature|signature)\s*:\s*)"
    r"(?P<value>[^\r\n]*)"
)
_SIGNATURE_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?P<key>[\w-]*(?:signature|sig|hmac|digest))(?P<quote>[\"']?)(?P<sep>\s*[=:]\s*)"
    r"(?P<value>(?:v\d+\s*[,=:]\s*)?\"(?:\\.|[^\"\\\r\n])*\"|"
    r"(?:v\d+\s*[,=:]\s*)?'(?:\\.|[^'\\\r\n])*'|(?:v\d+\s*[,=:]\s*)?[^\s,;|&]+)"
)
_REDIS_AUTH = re.compile(
    r"(?i)(?P<prefix>\bredis-cli\b" + _CMD_ARGS + r"(?:-a(?=[ \t=]|\S)|--pass(?:word)?(?=[ \t=])))"
    r"(?P<sep>[ \t]*=[ \t]*|[ \t]+)?(?P<value>\S+)"
)
_HTTP_AUTH = re.compile(
    r"(?i)(\b(?:http|https|xh)\b" + _CMD_ARGS + r"(?:-a|--auth)(?:[ \t]*=[ \t]*|[ \t]+)?)(\S+)"
)
_PASSWORD_COMMAND = re.compile(
    r"(?i)(?<!\w)(--password-command(?:[ \t]*=[ \t]*|[ \t]+))(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s;|&]+)"
)


def _redact_assignment(match: re.Match[str]) -> str:
    key = match.group("key").lower()
    raw = match.group("value")
    if key in {"cookie", "cookies"}:
        line_start = match.string.rfind("\n", 0, match.start()) + 1
        if re.search(r"(?i)\bcurl\b.*(?:-H|--header)(?:[ \t]+|=)[\"']?$", match.string[line_start:match.start()]):
            return match.group()
    if raw in {"{", "[", "("} or raw.strip() in {"{}", "[]", "()"}:
        return match.group()
    if raw.startswith(("(", "[")):
        close = ")" if raw.startswith("(") else "]"
        value = raw[1:-1] if raw.endswith(close) else raw[1:]
        if not _contains_secret_token(value):
            return match.group()
    if re.fullmatch(r"(?:num|total|min|max)[_-]?tokens?", key):
        return match.group()
    if key in {"authorization", "proxy-authorization"}:
        return match.group()
    if key.endswith("oauth") and raw.lower() in {"bearer", "basic", "token"}:
        return match.group()
    if raw.startswith(("<secret>", "<token>")):
        return match.group()
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    if value.lower() in {"bearer", "basic", "token", "apikey", "api-key"}:
        return match.group()
    if key in {"token", "tokens"} and value.isdigit():
        return match.group()
    if key in {"token", "tokens"} and not _looks_like_secret(value):
        line_end = match.string.find("\n", match.end())
        if line_end < 0:
            line_end = len(match.string)
        if re.match(r"[;|&][ \t]*<secret>", match.string[match.end():line_end]):
            return match.group()
    if key.endswith(("pass", "pw")) and not _contains_secret_token(value):
        return match.group()
    if key.endswith("signature"):
        return match.group()
    if not raw.startswith(("\"", "'")) and not _looks_like_secret(value):
        line_end = match.string.find("\n", match.end())
        if line_end < 0:
            line_end = len(match.string)
        if re.match(r"\s+[A-Z][a-z]+[;,]", match.string[match.end():line_end]):
            return match.group()
    if value.lower() in {"required", "true", "false", "yes", "no", "ok", "done", "started", "pending", "n/a", "passed", "success", "successful", "is", "was", "now", "wrong", "missing", "expired", "not", "valid", "revoked", "reset", "rotated", "unknown", "unavailable"}:
        return match.group()
    if key.endswith(("pass", "pw")) and value.isdigit() and re.match(r"(?i)\s+of\s+\d+\s+checks?\b", match.string[match.end():]):
        return match.group()
    if raw.startswith("\""):
        hidden = '"<secret>"'
    elif raw.startswith("'"):
        hidden = "'<secret>'"
    else:
        hidden = "<secret>"
    return match.group("key_quote") + match.group("key") + match.group("key_quote") + match.group("sep") + hidden


def _redact_credential_trailing(match: re.Match[str]) -> str:
    value = match.group("value")
    if value.startswith(("\"", "'")):
        quote = value[0]
        end_quote = re.search(r"(?<!\\)" + re.escape(quote), value[1:])
        if not end_quote:
            return match.group()
        end = end_quote.end() + 1
        status = value[1:end - 1].lower()
        tail = value[end:]
        if status in {"required", "true", "false", "yes", "no", "ok", "done", "started", "pending", "n/a", "passed", "success", "successful", "valid", "revoked", "reset", "rotated", "expired", "wrong", "missing", "unknown", "unavailable"}:
            masked_tail = _mask_tail_secrets(tail)
            if masked_tail != tail:
                return match.group("prefix") + value[:end] + masked_tail
        return match.group()
    if value.startswith(("{", "[", "(", "<secret>", "<token>")):
        return match.group()
    first = re.match(r"[^\s,;|&]+", value)
    if not first:
        return match.group()
    tail = value[first.end():]
    masked_tail = _mask_tail_secrets(tail)
    return match.group("prefix") + first.group() + masked_tail if masked_tail != tail else match.group()


def _redact_oauth(match: re.Match[str]) -> str:
    raw = match.group("value")
    if raw.startswith("(") and not _contains_secret_token(raw[1:].rstrip(")")):
        return match.group()
    if raw.startswith(("<secret>", "<token>")):
        return match.group()
    return match.group("prefix") + (match.group("scheme") or "") + "<secret>"


def _redact_prose_value(match: re.Match[str]) -> str:
    raw = match.group("value")
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    if not _contains_secret_token(value):
        return match.group()
    hidden = '"<secret>"' if raw.startswith('"') else "'<secret>'" if raw.startswith("'") else "<secret>"
    return match.group("key") + match.group("qualifier") + match.group("phrase") + hidden


def _redact_assignment_status(match: re.Match[str]) -> str:
    raw = match.group("value")
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    if not _looks_like_secret(value):
        return match.group()
    hidden = '"<secret>"' if raw.startswith('"') else "'<secret>'" if raw.startswith("'") else "<secret>"
    return match.group("prefix") + match.group("status") + " " + hidden


def _redact_credential_status_tail(match: re.Match[str]) -> str:
    raw = match.group("value")
    if raw.startswith(("<secret>", "<token>")):
        return match.group()
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    if not _looks_like_secret(value):
        return match.group()
    hidden = '"<secret>"' if raw.startswith('"') else "'<secret>'" if raw.startswith("'") else "<secret>"
    return match.group("prefix") + hidden


def _redact_credential_expression(match: re.Match[str]) -> str:
    return match.group("prefix") + "<secret>"


def _redact_short_pass(match: re.Match[str]) -> str:
    if match.group("key") == "P":
        return match.group()
    raw = match.group("value")
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    before = match.string[:match.start()]
    if (match.group("flag") == "-" and match.group("key").lower() == "p"
            and re.search(r"(?i)\b(?:mysql|mariadb|mysqldump)\b[^\r\n]*$", before)
            and re.fullmatch(r"[a-z][a-z0-9_-]*", value)):
        return match.group()
    if not match.group("flag") and not _contains_secret_token(value):
        return match.group()
    hidden = '"<secret>"' if raw.startswith('"') else "'<secret>'" if raw.startswith("'") else "<secret>"
    return (match.group("flag") or "") + match.group("key") + match.group("quote") + match.group("sep") + hidden


def _redact_signature(match: re.Match[str]) -> str:
    if match.group("key").lower() == "stripe-signature":
        return match.group()
    raw = match.group("value")
    if "(" in raw or ")" in raw or ("," in raw and not re.match(r"(?i)^v\d+\s*,", raw)):
        return match.group()
    value = raw[1:-1] if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0] else raw
    if len(value) < 4:
        return match.group()
    if re.fullmatch(r"(?i)(?:hmac(?:-sha\d+)?|sha(?:1|256|384|512)|base64|hex)", value):
        return match.group()
    if value.lower() in {"required", "n/a", "none", "null"} or not _looks_like_secret(value):
        return match.group()
    hidden = '"<secret>"' if raw.startswith('"') else "'<secret>'" if raw.startswith("'") else "<secret>"
    if re.match(r"(?i)v\d+\s*[,=:]", value):
        marker = re.match(r"(?i)v\d+\s*[,=:]\s*", value).group()
        hidden_value = marker + "<secret>"
    else:
        hidden_value = hidden
    return match.group("key") + match.group("quote") + match.group("sep") + hidden_value


def _redact_signature_header(match: re.Match[str]) -> str:
    prefix, value = match.group("prefix"), match.group("value")
    if re.match(r"(?i)stripe-signature\b", prefix):
        value = re.sub(r"(?i)(\bv\d+\s*=\s*)[^,\s]+", r"\1<secret>", value)
        return prefix + value
    if re.match(r"(?i)x-hub-signature\b", prefix):
        value = re.sub(r"(?i)(\bsha(?:1|256|384|512)\s*=\s*)[^,\s]+", r"\1<secret>", value)
        return prefix + ("<secret>" if value == match.group("value") else value)
    value = re.sub(
        r"(?i)(\b(?:v\d+\s*[,=:]\s*|sha(?:1|256|384|512)\s*=\s*|base64\s*[:=]\s*|"
        r"hmac(?:-sha\d+)?\s+|hmac(?:-sha\d+)?\s*[:=]\s*))([^,\s]+)",
        r"\1<secret>",
        value,
    )
    return prefix + value


def _redact_hawk_auth(match: re.Match[str]) -> str:
    return match.group("prefix") + "Hawk <secret>"


def _redact_http_auth(match: re.Match[str]) -> str:
    prefix, value = match.group(1), match.group(2)
    if ":" in value:
        user = value.rsplit(":", 1)[0]
        return prefix + user + ":<secret>"
    return prefix + "<secret>" if _looks_like_secret(value) else match.group()


def _redact_redis_auth(match: re.Match[str]) -> str:
    value = match.group("value")
    if match.group("sep") or _looks_like_secret(value):
        return match.group("prefix") + (match.group("sep") or "") + "<secret>"
    return match.group()


# Redaction runs on every key and note the ledger writes, and on miner samples. Order matters:
# whole secrets first, then structured credentials, then generic token patterns.
_REDACT = [
    # A PEM block (or a lone header someone pasted) is removed whole.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----)?", re.S),
     "<private-key>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "<token>"),  # JWT, any length
    (re.compile(r"[\w.+-]{1,64}@[\w-]+(\.[\w-]+)+"), "<email>"),
    (re.compile(r"://[^/\s:@]*:[^@\s]+@"), "://<cred>@"),
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <token>"),
    # Limit unquoted auth values to a scheme and one token so prose stays readable.
    (
        re.compile(
            r"(?i)\b(oauth)(\s*[=:]\s*)"
            r"(?!(?:bearer|basic|token)\s+(?:<token>|<secret>)|<secret>|\()"
            r"(?:(?:api[ _-]?key)\s+)?" + _SHELL_VALUE
        ),
        r"\1\2<secret>",
    ),
    (re.compile(r"(?i)\b((?:proxy-)?authorization)([\"']?)(\s*[=:]\s*)"
                r"(?!(?:[\"']?(?:bearer|basic|token)\s+<token>|[\"']?<secret>))"
                r"(?:(?P<double_quote>\")(?:\\.|[^\"\\\r\n])*(?P=double_quote)|"
                r"(?P<single_quote>')(?:\\.|[^'\\\r\n])*(?P=single_quote)|"
                r"Digest[ \t]+[\w-]+=(?:\"(?:\\.|[^\"\\\r\n])*\"|[^,\s\"']+)"
                r"(?:(?:[ \t]*[,;][ \t]*(?:\r?\n[ \t]*)?|[ \t]+|\r?\n[ \t]*)[\w-]+="
                r"(?:\"(?:\\.|[^\"\\\r\n])*\"|[^,\s\"']+))*|"
                r"[^\s\"']+(?:[ \t]+[^\s\"']+)?)"),
     _redact_authorization),
    # Keep the quoted shell argument intact before the Cookie rule sees it.
    (_CURL_COOKIE, r"\1\2\3<secret>\2"),
    (_CURL_COOKIE_ARG, _redact_curl_cookie_arg),
    (_ROOTPW_PLAINTEXT, r"\1<secret>"),
    (_PASSWORD_COMMAND, r"\1<secret>"),
    # curl and mysql credentials. _CMD_ARGS bounds each scan to one command, so text with
    # many "curl" words stays linear-time.
    (_CURL_USER, r"\1<secret>"),
    (re.compile(r"(?i)(\b(?:mysqladmin|mysql|mysqldump|mariadb)\b" + _CMD_ARGS + r"(?-i:-p)(?=\S))"
                + _SHELL_VALUE),
     r"\1<secret>"),
    (re.compile(r"(?i)(\bsshpass\b" + _CMD_ARGS + r"-p(?:" + _CMD_SEP + r"|=)?)" + _SHELL_VALUE),
     r"\1<secret>"),
    (re.compile(r"(?i)(\b(?:docker|podman)\b" + _CMD_ARGS + r"login\b" + _CMD_ARGS + r"(?:-p|--password)(?:" + _CMD_SEP + r"|=)?)"
                + _SHELL_VALUE),
     r"\1<secret>"),
    (_REDIS_AUTH, _redact_redis_auth),
    (_HTTP_AUTH, _redact_http_auth),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<token>"),
    (re.compile(r"\b(?:sk-proj-|sk-|ghp_|gho_|ghs_|ghu_|github_pat_|xox[abprs]-|glpat-)[A-Za-z0-9_\-]{8,}"), "<token>"),
    (re.compile(r"(?<![\w/+=])(?=[A-Za-z0-9_\-/+=]*\d)(?=[A-Za-z0-9_\-/+=]*[A-Za-z])[A-Za-z0-9_\-/+=]{32,}"), "<token>"),
    # Card numbers: 13-19 digits, optionally grouped with spaces or dashes.
    (re.compile(r"(?<![\w.])\d(?:[ -]?\d){12,18}(?![\w.])"), _redact_card),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"), "<ip>"),
    # IPv6: needs "::" or a hex letter, so clock times like 12:30:45 stay readable.
    (re.compile(r"(?i)(?<![\w:.])(?=[0-9a-f:]*(?:::|[a-f]))[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?![\w:])"), "<ip>"),
]


REDACT_MAX_CHARS = 4000   # callers keep at most 200 chars; the bounded prefix keeps regex cost fixed
_QUOTED_SECRET_START = re.compile(
    r"(?i)(?<![\w-])(?P<prefix>(?:-{1,2})?[\"']?(?:[\w-]*(?:password|passphrase|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|private[_-]?key|credentials?|cookies?|sessionid|authorization|authentication)"
    r"[\w-]*|sshpass|(?:[\w-]{1,64}[-_])?(?:pass|pw)|signature|"
    r"[\w-]*(?:oauth|auth(?:key|code|[-_](?:key|code))?|basic[-_]?auth)(?:[-_][\w-]+)?)[\"']?\s*[=:]\s*)(?P<quote>[\"'])"
)


def _bounded_prefix(text: str) -> str:
    """Clip regex input while replacing any quoted credential cut in half by the cap."""
    if len(text) <= REDACT_MAX_CHARS:
        return text
    prefix = text[:REDACT_MAX_CHARS]
    for match in _QUOTED_SECRET_START.finditer(prefix):
        quote = match.group("quote")
        escaped = False
        for pos in range(match.end(), len(prefix)):
            char = prefix[pos]
            if char == "\n":
                break
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                break
        else:
            return prefix[:match.end() - 1] + quote + "<secret>" + quote
    return prefix


def redact(text: str) -> str:
    text = _bounded_prefix(str(text)).replace(str(Path.home()), "~")
    text = _redact_yaml_blocks(text)
    text = _redact_yaml_nested_values(text)
    text = _redact_k8s_pairs(text)
    text = _redact_yaml_multiline_values(text)
    text = _redact_containers(text)
    text = _HAWK_AUTH.sub(_redact_hawk_auth, text)
    text = _HTTP_SIGNATURE.sub(_redact_signature_header, text)
    text = _PROSE_CREDENTIAL.sub(_redact_prose_value, text)
    text = _CREDENTIAL_STATUS_TAIL.sub(_redact_credential_status_tail, text)
    text = _OAUTH_ASSIGNMENT.sub(_redact_oauth, text)
    text = _ASSIGNMENT_STATUS.sub(_redact_assignment_status, text)
    text = _CREDENTIAL_EXPRESSION.sub(_redact_credential_expression, text)
    text = _CREDENTIAL_TRAILING.sub(_redact_credential_trailing, text)
    text = _CREDENTIAL_ASSIGNMENT.sub(_redact_assignment, text)
    text = _SHORT_PASS.sub(_redact_short_pass, text)
    text = _SIGNATURE_ASSIGNMENT.sub(_redact_signature, text)
    has_command_option = "-" in text
    for pat, sub in _REDACT:
        if not has_command_option and (pat is _CURL_COOKIE or pat is _CURL_USER):
            continue
        text = pat.sub(sub, text)
    return text


class _Lock:
    """An advisory lock around rotate-and-append, so two writers never rotate the same file twice."""

    def __init__(self, state: Path | None = None):
        self.state = preferred_state() if state is None else state

    def __enter__(self):
        self.fd = os.open(self.state / ".ledger.lock", os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            import fcntl
        except ImportError:  # no fcntl (Windows): appends are still atomic, rotation is best effort
            return self
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        try:
            while True:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"{self.state / '.ledger.lock'} held > {LOCK_TIMEOUT_S}s")
                    time.sleep(0.02)
        except BaseException:
            os.close(self.fd)  # a lock we never got must not leak its descriptor
            raise

    def __exit__(self, *exc):
        os.close(self.fd)  # closing releases the lock


def _rotate(state: Path | None = None) -> None:
    state = preferred_state() if state is None else state
    ledger, rotated = state / "ledger.jsonl", state / "ledger.1.jsonl"
    try:
        if ledger.stat().st_size >= ROTATE_BYTES:
            os.replace(ledger, rotated)
    except FileNotFoundError:
        pass


KEY_MAX = 80


def clip_key(key: str) -> tuple[str, bool]:
    """A key that fits KEY_MAX, and whether it was cut. A cut key keeps 71 characters plus "~" and
    an 8-character hash of the whole key, so distinct long keys stay distinct and the cut is visible."""
    if len(key) <= KEY_MAX:
        return key, False
    return key[:KEY_MAX - 9] + "~" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], True


def add(kind: str, key: str, note: str = "", agent: str = "") -> dict | None:
    """Append one row to the first state folder that takes it.

    Returns the row, or None when every state folder is read-only. A hook that
    cannot write its own ledger must not fail the agent's turn, so this never
    raises OSError: an agent seat with a read-only home keeps working.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    clipped, cut = clip_key(redact(key))
    row = {"ts": time.time(), "kind": kind, "key": clipped, "note": redact(note)[:200],
           "agent": redact(agent or os.environ.get("SELENITE_AGENT", ""))[:40]}
    if cut:
        row["truncated"] = True
    for state in state_dirs():
        try:
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            with _Lock(state):
                _rotate(state)
                fd = os.open(state / "ledger.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
            pane.broadcast("ledger.updated", {"kind": kind})
            return row
        except OSError:  # read-only home, full disk, no permission: the next folder may take it
            continue
    return None


def rows(days: int = 3650):
    """Yield well-formed rows newer than `days` from every state folder. Malformed lines are skipped."""
    since = time.time() - days * 86400
    for state in state_dirs():
        for path in (state / "ledger.1.jsonl", state / "ledger.jsonl"):
            yield from _read(path, since)


def signature() -> tuple:
    """A cheap fingerprint of every ledger file rows() reads. It changes whenever any of them does,
    so a cache keyed on it never misses rows written to a fallback state folder."""
    sig = []
    for state in state_dirs():
        for path in (state / "ledger.1.jsonl", state / "ledger.jsonl"):
            try:
                st = path.stat()
            except OSError:
                continue
            sig.append((str(path), st.st_mtime_ns, st.st_size, st.st_ino))
    return tuple(sig)


def _read(path: Path, since: float):
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not (isinstance(r, dict) and isinstance(r.get("kind"), str) and isinstance(r.get("key"), str)):
                continue
            ts = r.get("ts")
            if not isinstance(ts, (int, float)) or isinstance(ts, bool):
                continue
            if ts >= since:
                yield r


def fixed_keys(gate_last: dict[str, float] | None = None, source=None) -> set[str]:
    """Keys whose latest fix/reopen is a fix, and which no gate has hit since.

    Reads all history, not a window: a fix logged 40 days ago still counts in a
    7-day view, and a gate after the fix means the friction came back. An
    `approval` row after an `approval:<key>` fix reopens it the same way.
    `source` is an optional iterable of already-read rows (all history).
    """
    latest: dict[str, tuple[float, str]] = {}
    last_gate: dict[str, float] = dict(gate_last or {})
    for r in (rows() if source is None else source):
        k, key, ts = r["kind"], r["key"], r["ts"]
        if k in ("fix", "reopen"):
            if ts >= latest.get(key, (-1.0, ""))[0]:
                latest[key] = (ts, k)
        elif k in ("gate", "blocked"):
            last_gate[key] = max(last_gate.get(key, 0.0), ts)
        elif k == "approval":
            akey = "approval:" + key[:APPROVAL_KEY]
            last_gate[akey] = max(last_gate.get(akey, 0.0), ts)
    return {key for key, (ts, k) in latest.items() if k == "fix" and ts >= last_gate.get(key, 0.0)}


def summary(days: int) -> dict:
    by = Counter((r["kind"], r["key"]) for r in rows(days))
    return {"window_days": days, "top": [{"kind": k, "key": key, "n": n} for (k, key), n in by.most_common(25)]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("kind"); a.add_argument("key")
    a.add_argument("--note", default=""); a.add_argument("--agent", default="")
    s = sub.add_parser("summary"); s.add_argument("--days", type=int, default=30)
    sub.add_parser("state-dir", help="print the first state folder that accepts a write")
    ns = ap.parse_args()
    if ns.cmd == "add":
        row = add(ns.kind, ns.key, ns.note, ns.agent)
        if row and row.get("truncated"):
            print(f"ledger: key longer than {KEY_MAX} characters, stored as {row['key']!r}", file=sys.stderr)
        print(json.dumps(row))
    elif ns.cmd == "state-dir":
        state = writable_state()
        if state is None:
            return 1  # every folder is read-only: the caller prints the one line that fixes it
        print(state)
    else:
        print(json.dumps(summary(ns.days), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
