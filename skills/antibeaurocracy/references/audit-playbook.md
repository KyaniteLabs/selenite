# Audit playbook: every surface, every machine

Bureaucracy grows in three places: work queues, the rules agents load, and the conversation itself. A full audit covers all three on every machine an agent runs on. The steps below are read-only and run on any host.

## 0. Know the fleet

List the machines that run agents and mark the ones that are unreachable. An unreachable machine is a coverage gap, not a clean bill. Report it as a gap.

## 1. Work queues (Hermes kanban, or any board)

```bash
antibeaurocracy audit --json --top 40 > audit.json        # this host's Hermes homes
antibeaurocracy audit --root /other/hermes/home
```

Read the report in this order:
1. **blocked vs running.** A healthy board runs more than it blocks. More blocked than running means the gates are the bottleneck.
2. **shared causes.** One fix unblocks N cards. Do these first.
3. **created-blocked cards.** These were never attempted, so they are parking lots. Usually one actor makes most of them, so fix that actor's habit with `triage=true`.
4. **top fake gates.** These are sorted by confidence and age. Hand each one to the card's owner together with its one-line action.

For a board that isn't Hermes, export each blocked item's reason text and run `antibeaurocracy classify` on it.

## 2. Rules agents load

The default scan covers `~/.claude/CLAUDE.md`, `~/.claude/rules/`, `~/AGENTS.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.agents/rules/`, Kilo, and Hermes `SOUL.md` files, including every profile. Add skills with:

```bash
antibeaurocracy audit --skills          # also score every SKILL.md under the known skill dirs
```

What to look for:
- **High gate density together with an anti-gate clause.** The file says "no seat is an approval gate" and then lists twenty gates, so the anti-gate clause is out-voted. Delete gates rather than adding more anti-gate prose.
- **Approval chains.** Owner → seat → chief of staff → CEO. Each hop is an F2 relay waiting to happen.
- **Ratification language.** "Ratified", "countersigned" and "charter amendment" turn every change into a ceremony.

Fix each gate at its owning source. If you don't own the file, give the owner the evidence: file, line, gate count and the cards it produced.

## 3. The conversation

The Hermes plugin writes `plugin-data/antibeaurocracy/ledger.jsonl`, which records block attempts, declared kinds, questions asked and fail-opens (metadata only, never the reason text). A card that fails open after refusals is worth reading: either the classifier is wrong, or the agent kept insisting on a fake gate.

## 4. Other machines

Copy the repo or `pip install` it on each machine, run the same commands there, and merge the JSON. Over SSH:

```bash
ssh host 'antibeaurocracy audit --json' > audit-host.json   # after `pip install` of this repo on that host
```

Keep each machine's output private. It contains card titles and paths.

## 5. Report

The report starts with one line: blocked vs running and the fake share. Then give the three shared causes worth fixing first, then the rule deletions to propose, each with its owner. Name the coverage gaps explicitly. Do not unblock, close or edit anything you don't own. Hand the list over instead.
