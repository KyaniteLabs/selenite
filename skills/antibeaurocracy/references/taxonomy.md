# Taxonomy: WALL, HUMAN, MACHINERY, DEPENDENCY, FAKE

Every wait falls into exactly one class. The classifier checks the rules in a fixed order, and the order encodes the safety bias. This list mirrors `RULES` in `antibeaurocracy_core/classify.py`; a test keeps them in step.

1. **WALL** comes first. If any wall phrase matches, the verdict is WALL, whatever else the text says. Only a negator *directly* before the phrase, on the same line, denies it ("no spend involved", "not a force-push", "nothing to publish"). A negator never denies an absence that is itself the wall: "no budget approval yet", "no subscription seat left" and "no API key" are walls, unless the text says it isn't needed ("no payment needed", "no secrets in the diff"). One exception: an infra command (`terraform`, `kubectl`, `helm`) reported as failing, with no gate phrase anywhere, is MACHINERY. "Cannot proceed without deleting the prod database" and "no way around a force-push" are walls. A missed negation costs one pass; a false one would hide a wall.
2. **HUMAN**: a question aimed at a person ("Should I…?", "Which do you prefer…?", "Want me to…?", "OK to proceed?").
3. **DEPENDENCY**: an explicit task or card ID, or `kind=dependency`.
4. **WALL**: `kind=capability`, which Hermes defines as a hard wall (no access, missing credentials, an action no agent can do) that surfaces to a person. **MACHINERY**: `kind=transient`, a fault that may clear on its own. The declared kind is trusted.
5. **HUMAN**: a wait or gate phrase whose source is a person with authority ("Awaiting ACK from the CEO", "HOLD per the owner", "the founder's OK", "the CEO must countersign"). That is a person's call, not an agent gate, even when a fault is also mentioned. The role must be the source of the wait (after *from*, *per* or *by*, as a possessive, or as the subject): a bare noun ("the client to connect", "for the board update") does not count, and neither does an agent named after a role ("the CEO agent", "the CEO's agent").
6. **DEPENDENCY**: a HOLD with an explicit expiry ("until 2026-11-17"). It lapses on its own.
7. **HUMAN**: `kind=needs_input` with no gate or fault phrase in the text.
8. **MACHINERY**: a fault phrase with no gate phrase.
9. **FAKE** F1–F5: an agent-to-agent gate phrase. Confidence is 0.7–0.95, lowered by 0.15 when a fault also appears (the fault is real; the gate on top is still bureaucracy) and by 0.1 when filed as `needs_input`.
10. **FAKE default, not evidenced**: created blocked or empty is F5 at 0.5; older than 24h is F6 at 0.5; anything else is F6 at 0.3. The hooks act only on evidenced verdicts at or above `min_confidence` (default 0.6), and the audit counts these defaults as "unclear", not fake.

In `ask` mode the plugin doesn't argue with a verdict; it asks. An evidenced fake with no declared `kind` is handed back once with a question: is this a person's call (`kind=needs_input`), a hard wall no agent can pass (`kind=capability`), a dependency, a fault that should clear (`kind=transient`), or only another agent's OK? Whatever kind the agent declares goes through and is ledgered next to the regex verdict. The regex will keep missing some phrasing of a real wall; asking makes that miss cost one turn. Text with **any wall-family word** (money or a number of three or more digits, prod or infra, deletion, credentials, publishing, legal, freezes, or a person's role; agent and seat names such as "Product" or "the board agent" don't count) is only nudged, never asked. A declared kind is never nudged or asked, in any mode. The CLI audit can add an opt-in second opinion from any command you choose (`--judge`), listed as disagreements and never replacing the verdict.

## WALL: what counts

| Wall | Matches | Does not match |
|---|---|---|
| credentials | `ENEEDAUTH`, `HTTP 401/403`, `push=false`, `READ permission`, "missing/expired/invalid … token", "no API key", re-auth | the bare word "credential" in a custody note or capability ask |
| spend | billing, top-up, `402`, balance exhausted, paid plan, "cost roughly 3000", "cost about 3k", "$40/month", "3k per month", billing approval, "no budget approval" | a count per month with no money cue ("retries 3 per month") |
| publish | publish to npm/PyPI/GitHub/production/public, deploy to prod, `terraform apply/destroy`, `kubectl apply/delete`, `helm install/upgrade`, make the repo public, email or post externally, writing in the user's voice | an infra command reported as failing ("helm upgrade timed out", "kubectl apply dry-run failed"): that is MACHINERY |
| destructive | irreversible, force-push, `git push --force`, drop a database, delete a repo/data/history/backups/namespace/cluster/volume, "delete everything", wipe, purge | — (it errs toward the wall: even "deleted the merged branch" matches) |
| legal | legal review, licence compatibility, contract signature, ToS, GDPR | — |
| named-freeze | security hold, CEO freeze, code freeze, "FROZEN by", incident hold, e-stop | a generic HOLD (that is F5); lower-case "on hold" is not evidence of anything |

**Repo permission is a wall at the machinery owner, not a human decision for each card.** When one bot identity lacks push on nine repos, the result is nine wall verdicts with one shared cause. The fix is a single grant, not nine asks. The audit groups these under `repo-write-permission`.

## FAKE: edge cases

- **F1-ack vs. a real question.** A question is real when the human's answer would change what you do and you cannot pick a safe default. "Which of these two designs?" with no stated preference is real. "Want me to run the tests?" is F1.
- **F2-relay vs. a capability gap.** When your lane cannot push or open a PR, the gap is MACHINERY at the identity or permission owner. Asking a different seat to carry each patch turns one capability gap into a permanent relay. Fix the capability once.
- **F3-ownership-limbo.** "X must own/record/rule/declare" is limbo unless X is the human and the subject is a wall. Seats make calls with a default and a revert path. Disputes go in one comment to whoever the org chart names.
- **F4-ceremony.** Evidence a reader would actually check (a test run, a diff, a live URL) is not ceremony. Contracts about contracts, receipts for receipts, and re-verifying something already verified are.
- **F5-parking-lot.** Only an upper-case `HOLD` or `PARKED` marker counts as evidence. A HOLD with an expiry date ("until 2026-11-17") is legitimate and is not flagged. A HOLD with no expiry, a card created blocked "so it doesn't auto-dispatch" (use `triage=true` instead), and a block with no reason are all parking.
- **F6-stale-wait.** Done-but-stuck cards land here: "DONE, not blocked" and "PR complete, awaiting…". Close them.

## Why deterministic

The classifier is regex and rules, stdlib only, and runs in under a millisecond. It sits in a `pre_tool_call` hook, where an LLM call would add latency to every block and could not be audited. Its errors are visible and fixable one regex at a time. The audit report shows the matched phrases for every verdict.
