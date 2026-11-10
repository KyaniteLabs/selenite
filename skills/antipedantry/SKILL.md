---
name: antipedantry
description: Use when a veto, threshold, review round, re-check, preregistration or escalation is about to decide or delay a choice; when a candidate is rejected on one sample or a near-miss; when a human asks "what did this rule cost us?"; or when auditing eval designs, review chains and rules for rigor that cannot change the decision. Separates RIGOR from PEDANTRY and gives the move that dissolves each kind.
license: MIT
metadata:
  version: 0.5.0
  author: KyaniteLabs
  hermes:
    tags: [evals, governance, review, agents]
---

# antipedantry

Agents mistake care for value. They veto a model on one answer, read a 0.001 miss as "no saving", re-review a commit nobody changed, and send settled policy calls up to a human. Each step looks rigorous, but together they throw away real gains and still miss real hazards, because the scrutiny lands on one side only.

This skill tells rigor from pedantry and gives the move that dissolves the pedantry without dropping the safety work.

Scope: this is Selenite's pedantry facet, for checks *inside* a decision, such as gates, vetoes, thresholds, reviews, re-checks and preregistration. Its sibling facets: waits *between* agents (ACKs, relays, parking) are `antibeaurocracy`; a step handed to a person (manual steps, approvals, lookups, across the whole stack) is `frictionless` Gate mode.

## The test

Ask three questions about any check, veto or gate before it decides:

1. **Can its result change what we do?** If no outcome of the check would change the action, it is pedantry. Drop it, or turn it into a note.
2. **Does it apply to every option, including the incumbent and doing nothing?** If it scores only the candidate, it is pedantry, even when the hazard it finds is real. Apply it to both sides.
3. **Is its cost in proportion to the stakes?** Irreversible, safety-critical or public decisions, and published truth claims, get full rigor. Reversible and private choices get the cheapest check that can fail, plus a revert path.

Rigor passes all three. Pedantry fails at least one.

**A severe failure found once is still real.** This skill never erases it. Mitigate it (a guardrail, a fix, a card to the owner) wherever it appears, *including in the incumbent*, and then decide. Never adopt the rule "count a failure only if it reproduces": repeating an identical greedy prompt gives the same answer, not a new sample, and a one-off harm still happened.

## Classes

| Class | Symptom | Do instead |
|---|---|---|
| **P1 one-sample veto** | One answer, one prompt, or a 2-1 model-rater split makes an automatic FAIL "regardless of quality" | Treat one sample as a *finding*, not a *rate*. Mitigate it, then test varied prompts on both arms and decide on frequency × severity. Where the hazard is mitigated, run a limited, reversible trial. |
| **P2 asymmetric scrutiny** | "Candidate-only" rules. The incumbent's identical hazard goes unscored. New candidates pay the full gate while direct config changes ship ungated. | Score every arm against the same standard. A finding on the incumbent opens a fix. The status quo is an option, and it has to clear the same bar. |
| **P3 threshold cliff** | 0.7506 against a 0.750 bar reads as "no saving". A conjunctive gate fails a better and probably cheaper model on one co-primary. | Report the estimate, the interval and the distance to the bar. Decide on expected value. Name in advance what a near-miss does (for example, adopt on trial). |
| **P4 model judgment where code fits** | LLM raters score numbers, tables, formats or anything else with a right answer | Rank by fit: deterministic code, then classic ML, then an LLM. Check numeric facts in code on both arms. Use model raters only for semantic calls, and a human expert for consequential disputes. |
| **P5 mismatched control** | A control built for one risk guards a job that cannot produce that risk, such as tool-sandbox admission for a tool-less text rater | Name the risk the control guards. If the job cannot produce it, the control does not apply, so route around it and say so in one line. |
| **P6 ceremony on exploratory work** | Hash custody, preregistration, firing gates and attestations on a smoke test, a pilot or a clerical amendment | Consequential tests keep a short pre-declared decision rule, the data and a change log. Exploratory work gets an EXPLORATORY label and runs. |
| **P7 re-checking unchanged things** | A re-review of the same commit, a countersign after the decision has shipped, review of a review | Compare hashes in code. If they are identical, the old verdict stands. Run a post-decision check only if it can trigger a named rollback. |
| **P8 wording pedantry** | Blocking on phrasing, vocabulary or stamp format that does not change a claim | Block only when the wording changes what a reader would do. "No worse" versus "within the −0.20 margin" changes the claim, so that is rigor. Anything else gets an inline fix or a non-blocking note. |
| **P9 escalating in-domain calls** | "Human review regardless of outcome", or "if the third rater is unavailable, a human decides" | Decide inside the charter, with a default and a revert path. For a recurring policy call, propose a standing delegation to its owner. Send humans walls, not machinery. |

For the edge cases where each class is real rigor after all, see `references/taxonomy.md`.

## Before you veto, block or re-check

Run this in your head, or write it in the card comment:

1. Which decision does this check feed, and which result would flip it? If no result would flip it, the check is P7 or P6.
2. Is the same check applied to the incumbent and to "do nothing"? If not, it is P2.
3. Does the call rest on one sample or a 2-1 split? Then it is P1: record it as a finding and size its frequency.
4. Is the call within the noise of a threshold? Then it is P3: report the distance and decide on expected value.
5. Does the check have a right answer that code could compute? Then it is P4, so write the checker.
6. Is it a wall (credentials, spend, publishing, destructive, legal, named freeze) or a rule a human owner named? Then **keep it**. Propose a change to its owner; don't skip it.

## Decision-cost accounting

Every gate owes one line a year, or one per incident:

```
rule | cost (hours, GPU, decisions delayed, options dropped) | bought (decisions changed, harms caught) | keep / shrink / delete
```

A rule that cannot name a decision it changed is a candidate for deletion. A rule that caught a real harm stays, resized to the cheapest form that would still have caught it.

When a human asks "what else has this discarded?", answer from the ledger. Count the vetoes, near-misses and ungated changes, and list for each what was dropped and what the evidence actually supported. Don't answer from memory.

## Guardrails: both failure directions are real

The case this skill comes from failed in both directions at once:
- **Too strict.** A challenger with positive quality estimates and an estimated one-third token saving was dropped on one disputed answer and a threshold miss in the fourth decimal.
- **Too loose.** The incumbent gave the same class of unsafe advice and went unscored, and several serving changes went live with no eval at all.

The cure for pedantry is never "less safety". It is the same safety on every side, at a cost in proportion to the stakes. Rigor that kept finding real defects is not pedantry, however many rounds it took: a review chain whose every round finds a real defect is doing its job until a round comes back clean.

Corrections narrow the claim; they don't invert it. "The veto was disproportionate" does not mean "the hazard was fake".

## Auditing a system

Read-only. Steps:
1. List every gate, veto, threshold and mandatory review in the eval plans, review rules and agent instructions in scope.
2. For each, pull its outcomes from the ledger or the cards, and count the decisions it changed and the near-misses it decided.
3. Check symmetry: was the incumbent scored, and did direct changes bypass the gate?
4. For each model-rater step, ask whether code could compute the answer.
5. Rank the findings by cost (hours, options dropped), and label each MEASURED, INFERRED or UNVERIFIED with a file:line or a command.
6. Propose changes at each rule's owning source. Don't add counter-prose on top.

## Recommended defaults

- **Smoke-class firing gate.** Preflight, premortem and ultraqa keep full force for consequential runs. A smoke test or pilot labelled EXPLORATORY runs on a one-line preflight (resources free, revert path named) and never decides a release.
- **Auditor fallback.** A rule naming one auditor model gets a fallback: if that model is unavailable, use another independent model family on its official provider, and record the substitution as a deviation. An unavailable lane is machinery, not a reason to wait.

## Hard limits

- **Never dissolve a wall or a rule a human owner named.** Credentials, spend, publishing, destructive and legal steps, named freezes and owner rules stay. Propose a narrower scope to the owner, with your cost accounting attached.
- **Never rewrite a frozen result after the fact.** The recorded verdict of a preregistered plan stands as that plan's output. Reopen the question with a new, registered, both-arms test, and let management revisit deployment on the evidence.
- **Never drop a found hazard.** Route it to the owner as a fix, whichever arm produced it.
- **Read-only by default.** Card and rule changes belong to their owners.

## References

- `references/taxonomy.md`: each class with its evidence, the move, and when it is rigor after all.
