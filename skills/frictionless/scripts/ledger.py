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


_SECRET_KEY = (r"[\w-]*(?:password|passphrase|passwd|pwd|secret|token|api[_-]?key|"
               r"access[_-]?key|private[_-]?key|credentials?|cookies?|sessionid|"
               r"oauth|auth(?:key|code|[-_](?:key|code))?|basic[-_]?auth)[\w-]*")
_CREDENTIAL_CONTAINER = re.compile(
    r"(?i)(?<![\w-])(?P<prefix>[\"']?" + _SECRET_KEY + r"[\"']?\s*[=:]\s*)"
    r"(?P<open>[\[{(])"
)


def _container_end(text: str, start: int) -> int:
    """End of a bounded JSON/Python-style object or list, including nested values."""
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack = [pairs[text[start]]]
    quote = ""
    escaped = False
    for pos in range(start + 1, len(text)):
        char = text[pos]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in ("'", '\"'):
            quote = char
        elif char in pairs:
            stack.append(pairs[char])
        elif char in ("}", "]", ")"):
            if char != stack[-1]:
                end = re.search(r"[\s,;|&]", text[start:])
                return start + end.start() if end else len(text)
            stack.pop()
            if not stack:
                return pos + 1
    end = re.search(r"[\s,;|&]", text[start:])
    return start + end.start() if end else len(text)


def _redact_containers(text: str) -> str:
    """Replace complete recognized credential containers, including arbitrary nested leaves."""
    out = []
    cursor = 0
    for match in _CREDENTIAL_CONTAINER.finditer(text):
        if match.start() < cursor:
            continue
        end = _container_end(text, match.start("open"))
        if text[match.start("open")] == "[" and text[end:end + 1] == "(":
            continue
        out.append(text[cursor:match.start()])
        out.append(match.group("prefix") + '"<secret>"')
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


_YAML_SECRET_BLOCK = re.compile(
    r"(?i)^(?P<prefix>[ \t]*" + _SECRET_KEY + r"\s*:\s*)"
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
        parent_indent = len(match.group("prefix")) - len(match.group("prefix").lstrip(" \t"))
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
                if indent <= parent_indent:
                    break
                content_indent = indent
            if indent < content_indent:
                break
            j += 1
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        out.append(match.group("prefix") + "<secret>" + newline)
        i = j
    return "".join(out)


_K8S_SECRET_VALUE = re.compile(
    r"(?im)(?P<prefix>\bname\s*:\s*[\"']?" + _SECRET_KEY + r"[\"']?\s*\r?\n"
    r"[ \t]+value\s*:\s*)(?P<value>\"(?:\\.|[^\"\\\r\n])*\"|"
    r"'(?:\\.|[^'\\\r\n])*'|[^\s#]+)"
)


# Redaction runs on every key and note the ledger writes, and on miner samples. Order matters:
# whole secrets first, then the generic long-run rule.
_REDACT = [
    # A PEM block (or a lone header someone pasted) is removed whole.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----)?", re.S),
     "<private-key>"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "<token>"),  # JWT, any length
    (re.compile(r"[\w.+-]{1,64}@[\w-]+(\.[\w-]+)+"), "<email>"),
    (re.compile(r"://[^/\s:@]+:[^@\s]+@"), "://<cred>@"),
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 <token>"),
    # Limit unquoted auth values to a scheme and one token so prose stays readable.
    (
        re.compile(
            r"(?i)\b(oauth)(\s*[=:]\s*)"
            r"(?!(?:bearer|basic|token)\s+<token>|<secret>)"
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
    (re.compile(r"(?i)(?<![\w-])(?:(?P<flag>-{1,2})|(?<!-))(?P<key>(?!(?:bypass|compass|encompass|surpass|overpass|underpass|trespass|sshpass|rootpw(?=\s+--plaintext))\b)"
                r"(?:[A-Za-z0-9]{0,32}(?:pass|pw)|[\w-]{1,64}[-_](?:pass|pw)))"
                r"(?P<key_quote>[\"']?)(?P<sep>\s*(?:[=:]\s*|\s+))"
                r"(?!(?:[\"']?(?:is|was|now)\b|[\"']?(?:true|false|yes|no|ok|done|started|pending|n/a|passed|success|successful|required|missing|not applicable)[\"']?(?=\s*(?:$|[\s,;}\]]|#))|\d+\s+of\s+\d+\s+checks?\b))"
                r"(?!(?:[\"']?(?:bearer|basic|token)\s+<token>|[\"']?<secret>))"
                r"(?:(?P<double_quote>\")(?:\\.|[^\"\\])*?(?P=double_quote)|"
                r"(?P<single_quote>')(?:\\.|[^'\\])*?(?P=single_quote)|\S+)"),
     _redact_key_value),
    (re.compile(r"(?i)(?<![\w-])(?:(?P<flag>-{1,2})|(?<!-))(?P<key>[\w-]*signature)"
                r"(?P<key_quote>[\"']?)(?P<sep>\s*[=:]\s*)"
                r"(?!(?:[\"']?required\b))"
                r"(?:(?P<double_quote>\")(?:\\.|[^\"\\])*?(?P=double_quote)|"
                r"(?P<single_quote>')(?:\\.|[^'\\])*?(?P=single_quote)|"
                r"(?:(?:sha(?:1|256|384|512)|v\d+)[=:,]\s*[A-Za-z0-9_+/=-]+|"
                r"[A-Za-z0-9_+/=-]{8,}|(?=[A-Za-z0-9_+/=-]*[0-9_+/=-])[A-Za-z0-9_+/=-]+|"
                r"[A-Za-z0-9_+/=-])(?![A-Za-z0-9_+/=-]))"),
     _redact_key_value),
    # key=value / key: value. A value the bearer rule already replaced keeps its scheme word, so
    # "Authorization: Bearer <token>" stays readable.
    (re.compile(r"(?i)(?<!\w)(?:(?P<flag>-{1,2})|(?<!-))(?=[\w][\w-]*[\"']?\s*[=:])"
                r"(?!max[-_]?tokens?\b)(?!(?:tokenizer|(?:num|total|min|max)_tokens\w*)[\"']?\s*[=:])"
                r"(?P<key>(?:[\w-]*(?:password|passphrase|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credentials?|cookies?|sessionid)[\w-]*|"
                r"sshpass|"
                r"[\w-]*(?:oauth|auth(?:key|code|[-_](?:key|code))?|basic[-_]?auth)(?:[-_][\w-]+)?|authorization|authentication))"
                r"(?P<key_quote>[\"']?)(?P<sep>\s*[=:]\s*)"
                r"(?![\[{(])"
                r"(?![\"']?required[\"']?(?=\s*(?:$|[\r\n,}\]]|#)))"
                r"(?!(?:[\"']?(?:bearer|basic|token)\s+<token>|[\"']?<secret>))"
                r"(?:(?P<double_quote>\")(?:\\.|[^\"\\])*(?P=double_quote)|"
                r"(?P<single_quote>')(?:\\.|[^'\\])*(?P=single_quote)|\S+)"),
     _redact_key_value),
    (re.compile(r"(?i)(?P<key>\b(?:password|passphrase|passwd|pwd|pw|secret|token|(?:api|access|private)\s+key))"
                r"(?P<prefix>\s+(?:(?:is|was)\s+(?:(?:now|set\s+to)\s+)?|now\s+|(?:is|was|now)\s*:\s*))"
                r"(?!(?:required|wrong|missing|expired|not\s+set|unset|unknown|unavailable)\b)\S+"),
     r"\g<key>\g<prefix><secret>"),
    # "password hunter2" with no separator; a plain word ("password reset") is left alone.
    (re.compile(r"(?i)\b(password|passphrase|passwd)(\s+)(?!<secret>)(?!(?:is|was|now|required|wrong|missing|not)\b)(?=\S*[^\sA-Za-z])\S+"),
     r"\1\2<secret>"),
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
    (re.compile(r"(?i)(\bredis-cli\b" + _CMD_ARGS + r"(?:-a|--pass(?:word)?)(?=" + _CMD_SEP + r"|=)(?:" + _CMD_SEP + r"|=))"
                + _SHELL_VALUE),
     r"\1<secret>"),
    (re.compile(r"(?i)(\bhttps?\b" + _CMD_ARGS + r"(?:-a|--auth)(?=" + _CMD_SEP + r"|=)(?:" + _CMD_SEP + r"|=))(?=[^\s;|&]*:)" + _SHELL_VALUE),
     r"\1<secret>"),
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
    text = _K8S_SECRET_VALUE.sub(lambda m: m.group("prefix") + "<secret>", text)
    text = _redact_containers(text)
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
