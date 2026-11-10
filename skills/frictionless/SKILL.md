---
name: frictionless
description: Remove friction between a human and their agents. Use when a step needs the human (login, token, 2FA, approval, dashboard click, paste), when the human shows overload (cursing, typo bursts, "just do it", "stop asking", "you stopped"), when asked to find or fix friction in a workflow, repo or agent setup, or when asked to make something "friction free". Also runs a self-improvement loop that learns from transcripts and proposes upgrades to itself.
license: MIT
metadata:
  product: Selenite
  version: 0.1.0
---

# frictionless

Every second the human spends on something an agent could have done is a defect. This skill finds those seconds and removes them. It has four modes. Choose the mode from what triggered it. If two modes apply, run Calm first.

| Trigger | Mode |
|---|---|
| A step only the human can do, or a blocker that names the human | **Gate** |
| "Find the friction", "why is this slow", a repo or workflow audit | **Audit** |
| Overload signals in the human's last messages | **Calm** |
| Scheduled run, or `/frictionless evolve` | **Evolve** |

## Gate: shrink the human's step

Climb this ladder from the top and stop at the first rung that works. Never skip to a checklist because it's easy to write.

1. **Eliminate.** Can the step go away? Look for an existing credential, a cached token, an already-authorized tool, a service account or bot identity, or a different route that needs no human. Check before you ask.
2. **Automate.** Can the agent do it with access it already has? Do it.
3. **One shot.** If the human must act, give them exactly one thing: a single paste-ready command, or a single link with every field prefilled. It must be:
   - idempotent (safe to run twice),
   - self-verifying (it prints a clear PASS or FAIL at the end),
   - quiet about secrets (it reads them from a prompt or the clipboard and never echoes them),
   - runnable where the human is (say which machine; prefix with `! ` when the harness supports in-session shell).
4. **Guided.** Only when a one-shot is impossible (2FA on a phone, a CAPTCHA, a hardware key): give numbered steps, one action each, with the exact button text, and what the screen shows when it worked.

Then **verify it yourself** and resume the work without being asked. Batch every human step in the effort into one ask, never a drip. Log the gate (see Evolve).

Authority walls stay walls. Spending money, deleting things, publishing, changing visibility and minting new credentials still need explicit approval. Frictionless means fewer clicks for the human, never fewer checks.

## Audit: find friction and rank the fixes

1. Measure. Run `scripts/mine.py` (read-only, stdlib, low priority) on the transcripts available. Add `--path` for other logs. It writes an aggregate report and a private sample file. Read the samples locally. Never paste them anywhere shared.
2. Look past transcripts too: permission prompts that repeat, manual steps in READMEs and runbooks, waits with no reason, re-auth loops, and questions that a sensible default would have answered.
3. Rank each friction by how often it happens × the human time it costs, both measured.
4. Pick the fix by capability fit, cheapest first: **deterministic code** (a script, hook, allowlist, default) → **classic ML** (a classifier or threshold) → **LLM** (prompt or skill text). Prose is the last resort, because a rule in prose is a request, while a hook is a guarantee.
5. Ship the top fix, or propose it if it crosses an authority wall. Report it in one line: friction → fix → evidence.

## Calm: the human is overloaded

Signals (see `references/signals.md`): cursing, a burst of typos, very short commands ("just do it", "go"), repeated corrections, "you stopped", "I already told you".

A curse is a **late** marker. By the time one appears, the human's stated rules have usually been skipped several times. Treat it as a verdict on the work, not as a spec.

- Find the rule that was ignored, from the conversation and its instructions, and fix that first.
- No clarifying questions. Pick the sensible default, act, and state the default in one line.
- No apology paragraphs, no lectures, no option menus.
- Reply as: one-line result or blocker, then one next action. Park everything else.
- Verify against live state before claiming anything.
- On the second signal in a row, stop explaining and only act. Rage is sticky; breaking the chain matters more than being thorough in prose.

## Evolve: improve this skill

Selenite learns, but it never rewrites itself silently.

1. **Collect.** Every Gate, Calm and Audit appends one line to the ledger: `scripts/ledger.py add <kind> <short-key> [--note ...]`. The Hermes plugin also logs approval prompts, blocked Kanban tasks and overload signals automatically. The ledger lives in `$SELENITE_STATE` (default `~/.local/state/selenite`), outside the repo.
2. **Mine.** Run `scripts/mine.py` over the last N days.
3. **Propose.** Run `scripts/evolve.py`. It reads the ledger and the latest reports, and writes a proposal with the top recurring frictions, signal patterns that never fired (pruning candidates), and false positives that were recorded with `ledger.py add miss` or `fp`.
4. **Review.** Turn the proposal into a branch and PR against this repo. A human merges it. No auto-merge, no edits to the installed copy.
5. **Prune.** A signal or rule that has not fired, or has not helped, in two evolve cycles is removed (moved to `references/compost.md`). Rules re-earn their place.

## Personal profile

Per-person tuning (their known gates, preferred reply shape, extra signal words) belongs in `$SELENITE_HOME/profile.md` (default `~/.config/selenite/profile.md`). Load it when present. Never commit it, and never copy its contents into shared output.

## Files

- `references/signals.md`: overload and friction signals, with what each one means.
- `references/gate-recipes.md`: one-shot patterns for common human gates.
- `scripts/signals.py`: shared detector used by the scripts and the Hermes plugin.
- `scripts/mine.py`: transcript miner (Claude Code, Codex, Hermes, generic).
- `scripts/ledger.py`: append and summarize friction events.
- `scripts/evolve.py`: turn the ledger and reports into an improvement proposal.
