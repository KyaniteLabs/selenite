# Why Selenite, antibeaurocracy and antipedantry are one product

TLDR: three tools were asking the same question about three kinds of friction. Merged, they share one test, one set of walls, one ranked view and one off switch. This file records the intent, and what the merge surfaced: conflicts, gaps, silent failures and the open items still left.

## The one intent

Selenite takes friction off the human, treated as accessibility, and clears it at the source. Every facet applies one test: **does this step, wait or check earn its cost to the person?**

| Facet | Skill | What it clears | How it reaches the person |
|---|---|---|---|
| Gate | `frictionless` | Steps handed to a person: logins, approvals, copied tokens, manual runbook steps. | Directly. |
| Fake gates | `antibeaurocracy` | One agent parking work on another for a reason that isn't real. | Later, as a stale board the person has to untangle. |
| Pedantry | `antipedantry` | Checks that can't change the decision but still delay or escalate it. | As delay, or as an escalation the person has to rule on. |

**Walls always stand:** credentials, spend, publishing or deploying, destructive steps, legal, a named freeze, and questions only a person can answer. A wall is asked once, as a decision. No facet routes around one.

**One ranked view:** Cleanse ranks findings from the Gate and fake-gate facets by how often they land on the person. Pedantry is not in Cleanse yet (see Missed opportunities). **Two ledgers, one reader:** Selenite's ledger records gates, approvals, blocked cards and what cleared; the fake-gate facet keeps its own metadata ledger. Cleanse reads both. **One off switch:** the `hooks` setting or `SELENITE_HOOKS=0`. **One list of walls:** `WALLS` in `antibeaurocracy_core/classify.py` feeds Calm, the doctrine, the nudge and the question, and a test holds the skill text to it.

**One routing rule for a blocked card** (`lands_on_a_human` in `__init__.py`): a declared kind decides first. Hermes's `needs_input` and `capability` wait on a person; `dependency` and `transient` don't. Without one, an evidenced verdict decides: WALL and HUMAN wait on a person, DEPENDENCY and MACHINERY don't, and FAKE does only when the text also names a human step. With no evidence, the classifier's fallback isn't a finding, so Selenite's own human-step words decide.

## Conflicts and contradictions

| Finding | Status |
|---|---|
| Selenite counted "approval" on a blocked card as a human step; antibeaurocracy calls an approval between agents an F1 fake. | Fixed: `lands_on_a_human` routes by the evidenced verdict. |
| Both plugins registered `kanban_task_blocked`, so one block ran two observers. | Fixed: one observer calls `observe_block`. |
| A standalone antibeaurocracy plugin installed next to Selenite runs the fake-gate hooks twice. | Mitigated: `install.sh --hermes` warns. Disable the standalone plugin. |
| antibeaurocracy's `.gitignore` excluded `DESIGN-PREFLIGHT`, which Selenite tracks. | Fixed: not carried over. |
| The config key `mode` was ambiguous next to Selenite's modes. | Fixed: renamed `fake_gate_mode`; `ledger` renamed `fake_gate_ledger`. |
| The product is spelled `antibeaurocracy`; its tools are `bureaucracy_*`. | Kept both, so existing installs and scripts keep working. |
| antibeaurocracy says it "errs toward wall", but unevidenced text falls back to F6 (0.3) or F5 (0.5). "2FA code required" or "needs owner to log in" can land there. | Open, unfounded assumption. Mitigated: Cleanse counts only evidenced verdicts at confidence 0.6 or more, and the hooks act only on evidenced verdicts. |

## Gaps

| Finding | Status |
|---|---|
| antipedantry had no code and wasn't registered in Hermes. | Partly fixed: registered as a skill. It still has no code path. |
| antibeaurocracy's dashboard ignored the `enforce` alias for `ask`. | Fixed. |
| The dashboard manifest version was stale at 0.3.0. | Fixed: every version is 0.5.0 and a test checks they agree. |
| The fake-gate ledger was unbounded. | Fixed: rotates at 4 MB, written 0600. |
| The antibeaurocracy skill pointed to a separate human-queue product, which overlapped with the Gate facet. | Fixed: removed. |
| A Selenite blocked badge clears only on `kanban_task_completed`, so an archived or reassigned card stays "blocked". | Fixed: `on_kanban_task_updated` clears it on any status change, and the badge set reseeds from the ledger after a restart. |

## Silent errors and swallowed failures

| Finding | Status |
|---|---|
| Hook failures and the fake-gate ledger and snapshot writes logged at debug. | Fixed: they fail open at warning. |
| The rules audit skipped an unreadable file without a word. | Fixed: it reports the file and the error. |
| The dashboard swallowed config and ledger read errors. | Fixed: logged at warning; a missing ledger is an empty count. |
| `signals.py` drops an invalid user regex silently. | Open. |
| `judge.py` returns an empty answer on timeout or OSError, which reads as "no opinion". | Open; counted as `no_answer`. |
| `ledger.py` ignores FileNotFoundError. | Benign: no ledger yet. |

## Implicit state machines

- **Selenite ledger key:** gate, approval or blocked, then fix, then possibly reopened. The last event wins. An `approval` row after an `always` reopens `approval:<key>`. There is no enum. Open.
- **Fake-gate card in Cleanse:** the latest event wins. A fake block marks the card, an ask or a declared kind clears it, a fail-open leaves it as it was.
- **Calm streak:** in memory, per session, capped at 256 sessions. Lost on restart by design.
- **Fake-gate echo window:** `_recent_attempts` suppresses a duplicate ledger row for 60 seconds after `pre_tool_call` saw the same block, and carries the declared kind to `kanban_task_blocked`, which Hermes calls without one. A block Hermes rejects (`{"error": ...}`) drops its entry, so a later real block is still ledgered.
- **Evolve silence:** a category's silent-cycle count moves only when it was measured that cycle (a new miner report, or Calm rows for the Calm categories). A damaged state file resets.
- **Refusals:** explicit. `RefusalStore` counts per card on disk with a TTL.

## Bottlenecks

- The dashboard ran a full board audit on every request. Fixed: cached for 30 seconds.
- The dispatcher-tick snapshot audits every board. It runs off-thread, hourly by default (`snapshot_minutes`).

## Missed opportunities (not done)

- Put antipedantry's decision-cost line on Selenite's ledger, so pedantry shows up in Cleanse like the other two facets.
- One classifier for all three facets, instead of Selenite's signals plus the fake-gate rules.
- Cleanse could read live board audit counts, not only the ledger.

## Provenance

The fake-gate code, CLI and the two skills were imported as one squashed change from antibeaurocracy main @a564f2c, whose tree is identical to its 0.3.0. The import carries no history dependency. Future work on all three facets lands here.
