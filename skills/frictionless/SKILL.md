---
name: frictionless
description: Take friction off the human, treated as accessibility. Clears every tool in an agent stack so fewer manual steps, clicks, lookups and decisions reach the person. Use when asked to cleanse, audit or tune the skills, plugins, hooks, permission allowlists, runbooks or workflows other agents use; when a step needs the human (login, token, 2FA, approval, dashboard click, paste); when the human shows overload (cursing, typo bursts, "just do it", "stop asking", "you stopped"); or when asked to make something "friction free". Needs no cleansing itself.
license: MIT
metadata:
  product: Selenite
  version: 0.5.0
---

# frictionless

Friction is any effort a person spends that a tool could have spent: a manual step, a login, a pasted token, a dashboard click, a command to remember, a wall of text to read, a question to answer. Treat it as an accessibility problem, not only an agent-to-agent one. Each step removed helps the person who is tired, overloaded, on a phone, using a screen reader or keyboard only, or working with ADHD or another disability. Every second the human spends on something an agent could have done is a defect.

Selenite is the stone people use to clear and recharge their other stones. This skill does the same for an agent stack: it clears friction out of every tool, agent, skill, plugin and workflow, so the work stops landing on the human.

Three outcomes, from the stone:

- **Cleanse:** every other tool gets checked and cleared.
- **Clarity:** one ranked view of what costs the human most, across the whole stack.
- **Calm:** fewer and smaller human steps, and replies short enough to take in at a glance.

**Selenite needs no cleansing.** This is a requirement. Never hand the human upkeep for Selenite itself: no setup steps after install, no state to prune, no findings about Selenite. Its state trims itself and CI keeps its own skill clean.

Selenite has three facets of one test (does this step, wait or check earn its cost to the human?), so nothing is done twice. This skill owns what lands on the human: their steps, clicks, lookups and approvals, across every tool in the stack. Waits *between* agents (ACKs, relays, parking) are the `antibeaurocracy` facet. Rigor *inside* a decision that can't change it (one-sample vetoes, threshold cliffs, re-checks of unchanged work) is the `antipedantry` facet. A pedantic check that ends in "a human decides" is both: hand the check to `antipedantry` and the human step to Gate.

Pick the mode from what triggered it. If Calm applies, run it first.

| Trigger | Mode |
|---|---|
| "Cleanse", "audit", "tune my setup", "why is this slow", a scheduled sweep | **Cleanse** |
| A step only the human can do, or a blocker that names the human | **Gate** |
| Two overload signals (see below) | **Calm** |
| Scheduled run, or `/frictionless evolve` | **Evolve** (optional: sharpen Selenite) |

## Cleanse: clear the other stones

1. **Sweep.** Run `scripts/cleanse.py` (read-only, stdlib). It checks every agent home it finds, and adds runbooks with `--path`. It reports these stones:
   - **Skills:** missing or misplaced frontmatter, a name that doesn't match the folder, descriptions longer than loaders keep, broken file references, dangling links, and copies that drifted apart.
   - **Plugins:** missing or legacy manifests, empty folders and dangling links.
   - **Hooks:** hook scripts that no longer exist, which fail on every call.
   - **Approvals** the human keeps giving, and **gates** that keep coming back (from the ledger).
   - **Runbooks** that tell a human to do manual steps.
   - **Fake gates**: cards the `antibeaurocracy` facet's ledger saw blocked on another agent with no real wall (counted once per card, confident verdicts only).
2. **Rank.** Measured interruptions come first, then structural faults by how often they bite (every call, every use, sometimes, drift). The result is the clarity view.
3. **Recharge.** Take the top finding and clear it in the repo that owns that stone, as a reviewable change: a fixed frontmatter, a restored script, an allowlist entry, a one-shot command in a runbook. Choose the fix by capability fit, cheapest first: **deterministic code** (a script, hook, allowlist or default) → **classic ML** (a classifier or threshold) → **LLM** (prompt or skill text). Prose is the last resort, because a rule in prose is a request while a hook is a guarantee.
4. Report in one line: stone → fix → evidence. Cleanse never edits another owner's files silently. A change outside the human's own repos is a proposal.

Transcripts show where the human paid. Run `scripts/mine.py` (read-only, low priority) to count friction in Claude Code, Codex and Hermes sessions. Its samples are private: read them locally and never paste them anywhere shared.

## Gate: shrink the human's step

Climb this ladder from the top and stop at the first rung that works. Never skip to a checklist because it's easy to write.

1. **Eliminate.** Can the step go away? Look for an existing credential, a cached token, an already-authorized tool, a service account or bot identity, or a route that needs no human. Check before you ask.
2. **Automate.** Can the agent do it with access it already has? Do it.
3. **One shot.** If the human must act, give them exactly one thing: a single paste-ready command, or a single link with every field prefilled. It must be:
   - idempotent (safe to run twice),
   - self-verifying (it prints PASS or FAIL in words, never colour or an emoji alone),
   - quiet about secrets (read from a prompt, never echoed, never in argv),
   - runnable where the human is (say which machine),
   - accessible: keyboard only, no timeouts or races, plain words a screen reader can speak, nothing to memorise or retype.
4. **Guided.** Only when a one-shot is impossible (2FA on a phone, a CAPTCHA, a hardware key): numbered steps, one action each, with the exact button text and what the screen shows when it worked. Never "click the blue button": name it.

Then **verify it yourself** and resume without being asked. Batch every human step in the effort into one ask, never a drip. Log the gate: `scripts/ledger.py add gate <key>`. A gate that repeats becomes a cleanse finding.

Walls stay walls. The walls are credentials, spending money, publishing, deploying or changing visibility, deleting or other irreversible steps, legal, a named freeze, and a question only a person can answer. Each still gets one short question to a person. Frictionless means fewer clicks for the human, never fewer checks.

## Calm: the human is overloaded

Signals (see `references/signals.md`): cursing, a burst of typos, "just do it", "stop asking", "you stopped", "I already told you". **One signal is information.** Switch to Calm on two distinct signals in one message, or a signal in two messages in a row.

A curse is a **late** marker. By then the human's stated rules have usually been skipped several times. Treat it as a verdict on the work, not a spec.

- Find the rule that was skipped, from the conversation and its instructions, and fix that first.
- No clarifying questions. Pick the sensible default, act, and state it in one line.
- No apology paragraphs, lectures or option menus.
- Reply with a one-line result or blocker, then one next action. Park the rest.
- Verify against live state before claiming anything.
- Walls still stand in Calm and still get one short question. Calm drops the other questions, never the walls.

## Evolve (optional): sharpen Selenite

Evolve improves Selenite's signals. It is optional: Selenite needs no cleansing, so skipping Evolve degrades nothing and never creates a task for the human. It never rewrites itself silently.

1. **Collect.** Gate, Calm and Cleanse append to the ledger in `$SELENITE_STATE` (default `~/.local/state/selenite`, outside the repo). The Hermes plugin also logs approvals a person granted once or for a session on a safe command (allowlist candidates; denials, timeouts, the smart approver, payments, MCP prompts and Hermes's own dangerous-command keys are never logged), Kanban tasks blocked on a person, and overload. Calm stays off inside a Kanban worker, where no person is reading. Record mistakes with `ledger.py add miss <key>` and `ledger.py add fp <key>`.
2. **Sweep.** Run `scripts/mine.py` and `scripts/cleanse.py`. Selenite's own skills are held clean by CI (`needs_no_cleansing()`); the sweep scans them like any other stone, so drift on one machine still shows up. Each cleanse run writes a report and one ledger row with its finding count.
3. **Propose.** Run `scripts/evolve.py`. It writes a proposal from the ledger, the newest miner report and the newest cleanse report. It also counts how many cycles in a row each signal category stayed silent. Silence only counts when it was measured: every category when a new miner report arrived, the Calm categories when Calm logged anything.
4. **Review.** Draft the accepted changes on a local branch of this repo. Opening a PR is the human's decision, and a human merges it. There is no auto-merge, and the installed copy is never edited.
5. **Prune.** A category silent for two cycles is proposed for `references/compost.md`. Rules have to keep earning their place. Selenite's own files (ledger, reports, samples, proposals) trim themselves and never need a human.

## Personal tuning

- **Extra signal words:** `$SELENITE_HOME/signals.txt` (default `~/.config/selenite/signals.txt`), one `<category>\t<regex>` per line. They load at runtime.
- **Profile:** `profile.md` in the same folder holds the person's known gates and preferred reply shape. No script reads it. The agent reads it when present, and it is never committed or copied into shared output.

## Files

- `references/signals.md`: overload signals and what each one means.
- `references/gate-recipes.md`: one-shot patterns for common human gates.
- `references/compost.md`: pruned rules, kept so they can be replanted.
- `scripts/cleanse.py`: the cleanse pass and clarity ranking.
- `scripts/signals.py`: the shared overload detector.
- `scripts/mine.py`: transcript miner (Claude Code, Codex, Hermes, generic).
- `scripts/ledger.py`: append and summarize friction events.
- `scripts/evolve.py`: Selenite's self-cleanse proposal.
