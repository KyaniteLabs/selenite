---
name: antibeaurocracy
description: Use when an agent is about to block, park, hold, relay, ask for an ACK or wait on another seat; when a board has more blocked than running work; when a human complains the agents are bureaucratic; or when auditing rules, SOULs and skills for gate language. Classifies each wait as WALL / HUMAN / MACHINERY / DEPENDENCY / FAKE and tells you what to do instead.
license: MIT
metadata:
  version: 0.6.0
  author: KyaniteLabs
  hermes:
    tags: [kanban, governance, agents]
---

# antibeaurocracy

Agents stop work for reasons that are not real. They ask permission for reversible work, they hand a finished patch to another seat to carry, they wait for someone to "own a ruling", and they park cards with no owner and no expiry. Each stop looks responsible, but together they leave a board where blocked work far outnumbers running work.

This skill tells a real wall from bureaucracy and gives the move that dissolves the bureaucracy.

Scope: this is Selenite's fake-gate facet, for waits between agents, seats and boards. Its sibling facets: rigor that cannot change a decision (one-sample vetoes, threshold cliffs, re-checks of unchanged work) is `antipedantry`; a step handed to a person (manual steps, approvals, lookups, across the whole stack) is `frictionless` Gate mode. When the honest answer is WALL or HUMAN, the wait is real: ask the person once, then let Gate make that step smaller next time.

## The rule

A wait is legitimate when it is one of these four:

| Class | What it is | Do |
|---|---|---|
| **WALL** | Credentials that fail or are missing, spend, publishing or external communication, destructive or irreversible action, legal, or a named freeze | Ask the human once: one line, decision only, with the options and your default. Keep doing every other part of the work. |
| **MACHINERY** | A broken tool, a missing GPU, a read-only filesystem, an unsupported ops action | Fix it or reroute to a lane that can do it. File the repro with the machinery owner. Don't ask permission to fix a bug. |
| **DEPENDENCY** | Another task has to land first | Link the parent with kind=dependency so the card resumes automatically. |
| **HUMAN** | A question only a person can answer (a preference, a choice with no safe default), a stop or OK from a person with authority ("HOLD per the CEO"), or anything filed as `kind=needs_input` | Ask it once, as one line with the options and your default. This skill never treats it as bureaucracy. |

Every other wait between agents is **FAKE**. There are six kinds:

| Subtype | Looks like | Do instead |
|---|---|---|
| F1-ack | "Awaiting approval from Product", "pending ACK from Platform": another agent's OK on work in your scope | Check scope and reversibility yourself. If it is yours and can be undone, do it and note how to undo it; if not, it is a wall. Questions to a person ("Want me to…?", "OK to proceed?") are HUMAN, not F1. |
| F2-relay | "Await the release agent to open the PR from my patch" | Do the carry step yourself. If your lane can't, ask the machinery owner once for the capability. |
| F3-ownership-limbo | "Product must record the ruling", "jointly adopt", "which seat owns" | Make the call with a stated default and a revert path, comment it on the card, and move on. |
| F4-ceremony | Attestations, receipt chains, review-of-review, contract-wording mismatches | Keep only evidence a reader would check, such as a test run, a diff or a URL. Comment instead of opening a card. |
| F5-parking-lot | Created blocked, HOLD with no owner and expiry, no reason given | Dispatch it, put it in triage, or close it. A hold needs a named owner and an expiry date. |
| F6-stale-wait | Waiting more than 24h with no named next actor | Name the next actor and action in one line, or close the card. |

A wall always wins: when a reason mentions both a wall and a fake pattern, it is treated as a wall. A negator directly before a wall phrase ("no spend involved") denies it; anything looser ("cannot proceed without deleting") still counts as the wall. The classifier is regex-based, so it can miss phrasings in either direction. It is built to err toward calling something a wall, and its advice never says a step is safe; it tells you to check scope and reversibility yourself.

## Before you stop: the check

Run the check before every block, hold, relay or question to the human:

```bash
antibeaurocracy classify "<your block reason>"            # any shell, any agent
```

In Hermes, call the `bureaucracy_classify` tool or type `/fake-gate <reason>`.

If you have no shell, run the same check in your head:
1. Is this credentials, spend, publishing or deploying, destructive, legal or a named freeze? Then it is a WALL: ask once.
2. Is it a question only a person can answer, where their answer would change what I do? Then it is HUMAN: ask once.
3. Am I waiting on a specific task ID? Then it is a DEPENDENCY, so link it.
4. Is something actually broken, or does my lane lack a capability? Then it is MACHINERY, so fix it or reroute.
5. Am I only waiting for another agent's OK, relay, ruling or ceremony, on a step that is in my scope and can be undone? Then it is FAKE. Do the action in the table above.
6. If none of these fits cleanly, treat it as a wall and ask once.

## Auditing a whole system

```bash
antibeaurocracy audit                 # read-only: boards in the active Hermes home (--all-homes: every ~/.hermes*), plus rule files
antibeaurocracy audit --json --top 40
antibeaurocracy audit --root /path/to/hermes-home --rules path/to/AGENTS.md
```

The audit reports four things:
- blocked vs running work;
- the share of blocked work that is fake;
- **shared causes**, where one fix unblocks many cards (for example, one bot identity without push rights);
- instruction files ranked by gate-language density.

Fix the shared causes first, because each one is the cheapest unblock per card. For the rule files, delete gate clauses at their owning source; don't add more anti-gate prose on top. A file that already carries an anti-gate clause and still has a high gate density is out-voting itself.

For the full multi-surface, multi-machine procedure, see `references/audit-playbook.md`.

## Hard limits

- **Read-only by default.** The audit never writes a board, card or file. Card actions (unblock, close, comment) belong to whoever owns the card.
- **Never dissolve a WALL or a HUMAN question.** Credentials, spend, publishing, destructive, legal, named freezes and real questions stay with the person. Make the ask decision-only and batch it.
- **Don't edit another seat's charter or SOUL on your own.** Propose the deletion to the owner, with the evidence from the audit.
- **Coordinate.** If another agent is already unblocking the same board, split the work: one acts on cards, the other ships tooling and lists.

## References

- `references/taxonomy.md`: the classes and their edge cases, and why the order of checks matters.
- `references/audit-playbook.md`: how to audit every surface on every machine.
- `references/research-2026-11.md`: what the field knows about approval fatigue, over-asking and multi-agent coordination cost, with sources.
