"""The plugin's gate state machine and its two small stores, made explicit.

One block attempt goes through ``decide``:

    mode      verdict over threshold   prior refusals   ->  state       refusals after
    observe   any                      any                  PASS        unchanged
    any       no                       any                  PASS        unchanged
    nudge     yes                      any                  NUDGE       unchanged
    ask       yes                      n < max              ASK         n + 1
    ask       yes                      n >= max             FAIL_OPEN   unchanged

ASK returns the block once with a question about what kind of wait it is; the plugin passes any
block that declares a kind before it reaches this table.

Refusal counts persist per card on disk (workers respawn, so an in-process counter would reset
and refuse forever). Nudges live in memory only for the span of one tool call.
"""

from __future__ import annotations

try:
    import fcntl
except ImportError:  # Windows: no advisory locks; refusal counts are still written atomically
    fcntl = None  # type: ignore[assignment]
import json
import os
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path


class GateState(str, Enum):
    PASS = "pass"
    NUDGE = "nudge"
    ASK = "ask"
    FAIL_OPEN = "fail_open"


def decide(mode: str, fake_over_threshold: bool, prior: int, max_refusals: int) -> tuple[GateState, int]:
    """Pure transition function. Returns the state and the refusal count after this attempt."""
    if mode == "observe" or not fake_over_threshold:
        return GateState.PASS, prior
    if mode == "nudge":
        return GateState.NUDGE, prior
    if mode in ("ask", "enforce"):
        if prior < max_refusals:
            return GateState.ASK, prior + 1
        return GateState.FAIL_OPEN, prior
    return GateState.PASS, prior  # unknown mode fails open


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _num(v, default: float = 0.0) -> float:
    """A finite float from whatever is on disk; anything else is ``default``."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f and f not in (float("inf"), float("-inf")) else default


class LockTimeout(OSError):
    """The refusal file lock stayed held past the timeout."""


class RefusalStore:
    """Per-card refusal counts in a JSON file, safe across threads and processes.

    Entries older than ``ttl_s`` are evicted on every write, so a card that was refused last week
    starts fresh and the file can't grow without bound.
    """

    # One lock per process, not per instance: the plugin builds a fresh store for each call.
    _LOCK = threading.Lock()

    def __init__(self, path: Path, ttl_s: float = 7 * 86400, max_entries: int = 5000,
                 lock_timeout_s: float = 2.0):
        self.path = Path(path)
        self.lock_timeout_s = lock_timeout_s
        self.ttl_s = ttl_s if ttl_s > 0 else 7 * 86400  # <=0 would evict every count: never fail open
        self.max_entries = max_entries

    def _load(self, now: float) -> dict:
        """Live entries only, each coerced to ``{"n": int >= 0, "ts": float}``. A malformed or
        expired entry is dropped, so a hand-edited or half-written file can't raise."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for k, v in (data.items() if isinstance(data, dict) else ()):
            if not isinstance(v, dict):
                continue
            ts = _num(v.get("ts"))
            if now - ts > self.ttl_s:
                continue
            out[str(k)] = {"n": max(0, int(_num(v.get("n")))), "ts": ts}
        return out

    def get(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return self._load(now).get(key, {}).get("n", 0)

    def _acquire(self, fh) -> None:
        if fcntl is None:  # the thread lock still serialises writers inside one process
            return
        deadline = time.monotonic() + self.lock_timeout_s
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"{self.path} lock held > {self.lock_timeout_s}s")
                time.sleep(0.02)

    def transition(self, key: str, fn, now: float | None = None):
        """Read the count, apply ``fn(prior) -> (state, new_count)`` and write it, under one lock."""
        now = time.time() if now is None else now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._LOCK.acquire(timeout=self.lock_timeout_s):
            raise LockTimeout(f"{self.path} thread lock held > {self.lock_timeout_s}s")
        try:
            # 0600 like every other file Selenite writes; open() alone would follow the umask
            with os.fdopen(os.open(self.path.with_suffix(".lock"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a") as lk:
                self._acquire(lk)
                try:
                    data = self._load(now)
                    prior = data.get(key, {}).get("n", 0)
                    state, n = fn(prior)
                    if n != prior:
                        data[key] = {"n": n, "ts": now}
                    if len(data) > self.max_entries:
                        keep = sorted(data.items(), key=lambda kv: kv[1]["ts"])[-self.max_entries:]
                        data = dict(keep)
                    atomic_write(self.path, json.dumps(data, separators=(",", ":")))
                    return state, n
                finally:
                    if fcntl is not None:
                        fcntl.flock(lk, fcntl.LOCK_UN)
        finally:
            self._LOCK.release()


class NudgeBox:
    """Notes waiting to be appended to one tool call's result. In memory, short-lived, bounded."""

    def __init__(self, ttl_s: float = 600, max_entries: int = 256):
        self.ttl_s = ttl_s
        self.max_entries = max_entries
        self._items: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def put(self, key: str, note: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._evict(now)
            self._items[key] = (now, note)
            while len(self._items) > self.max_entries:
                self._items.pop(next(iter(self._items)))

    def pop(self, key: str, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        with self._lock:
            self._evict(now)
            item = self._items.pop(key, None)
        return item[1] if item else None

    def _evict(self, now: float) -> None:
        stale = [k for k, (ts, _) in self._items.items() if now - ts > self.ttl_s]
        for k in stale:
            del self._items[k]

    def __len__(self) -> int:
        return len(self._items)
