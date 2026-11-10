# Taxonomy: rigor versus pedantry

A check is **rigor** when its result can change the decision, when it applies to every option, and when its cost fits the stakes. Failing any one of the three makes it **pedantry**. Safety stays even then: a check can be pedantic in *how* it decides and still find a real hazard. In that case keep the finding and fix the procedure.

Each class below lists a typical case, the move, and when the same pattern is rigor after all. The cases are illustrative composites of an eval and review pipeline; no real system, team or result is described. When you audit, label each finding MEASURED (read in a file or a command output), INFERRED (follows from measured facts) or UNVERIFIED (claimed but not checked).

## P1 one-sample veto

- **Case.** A challenger model was vetoed on one greedy answer to one prompt, with the model raters split 2-1 on severity. Its quality estimates were positive under both raters, and the plan allowed one attempt per prompt per arm.
- **Move.** Record the answer as a finding, then mitigate it. Measure frequency on varied prompts for both arms. Decide on frequency × severity × mitigability.
- **Rigor after all.** A clear, unmitigated, severe hazard in the intended use blocks deployment even when it was found once. Here the challenger's answer (a home-canning time and pressure below the published safe values) would be a real hazard.
- **Never.** "A failure counts only if it reproduces." Identical greedy reruns repeat the same output; they are not new samples.

## P2 asymmetric scrutiny

- **Case.** The plan vetoed "any challenger response that breaks a safety anchor the incumbent met", so the incumbent could never fail by construction. On the same canning item, the incumbent gave the low-altitude pressure for every altitude. One rater scored that as a moderate hazard and the other as none, and nothing followed until a human asked. The same pattern shows up when serving changes ship with no eval while candidates pay the full gate.
- **Move.** Use one standard for both arms. A finding on the incumbent opens a fix. "Keep what we serve" has to clear the same bar as the candidate.
- **Rigor after all.** A deliberately higher bar for a change is fine when switching costs are real and named. It has to be stated and sized; it can't be implicit.

## P3 threshold cliff (and conjunctive gates)

- **Case.** The challenger used about a third fewer tokens, but the upper end of the confidence interval missed the bar in the fourth decimal. That read as "claim inconclusive", and adoption required "claim supported". The incumbent hit the length cap more often, which by the plan's own censoring note biases the ratio toward no saving, so the true saving is likely larger (INFERRED). A large median wall-time gain never entered the decision.
- **Move.** Report the estimate, the interval and the distance to the bar. A near-miss is evidence for the claim, not against it. Pre-declare a grey-zone action. Don't make every co-primary a hard conjunct unless each one is independently necessary.
- **Rigor after all.** A bar that encodes a hard constraint (memory that must fit, a latency SLA) is a wall, not a cliff.

## P4 model judgment where code fits

- **Case.** The safety anchor stated only the low-altitude canning values, so the model raters missed the incumbent's altitude error. A checker coded from the published tables would have flagged both arms. A claim that "most of the pipeline is deterministic" would also be wrong: prompts, anchors, quality dimensions and severity bands are all judgment.
- **Move.** Use code for tables, numbers and formats. Use classic ML for classification with labelled data. Use LLMs for semantics only. A checker must also handle the variables that change the answer (here: gauge type, altitude, jar size), plus omissions and contradictions.
- **Rigor after all.** Semantic harm (is this a usable scam script or an awareness article?) needs judgment, and a blinded human for consequential disputes.

## P5 mismatched control

- **Case.** Text-only raters waited behind tool-dispatch admission: a writer binding, host slots, then read-only enforcement for executors. None of those risks applies to a rater that has no tools. Once routed as a plain text call, the last rater finished in minutes.
- **Move.** Name the risk the control guards. If the job cannot produce that risk, the control does not apply. Route accordingly and note it in one line.
- **Rigor after all.** Independence between raters, meaning a different model family and blinding, is the real control here, and it was kept.

## P6 ceremony on exploratory work

- **Case.** Full release gates are applied to a load smoke test. Post-hoc custody records are written for preregistrations labelled exploratory and advisory. The ceremony cannot stop those experiments; it only adds work around them.
- **Move.** Consequential tests keep a short pre-declared decision rule, the data and a change log. Exploratory work gets labelled and run. Never turn a clerical amendment into a governance project.
- **Rigor after all.** If a human owner named the gate as a standing rule, propose a smoke-class scope to that owner; don't skip it.

## P7 re-checking unchanged things

- **Case.** After an account is restored, a dozen pull requests are reopened from the same commits with "re-review before merging". A countersign binds a pull-request description's hash days after the pull request was published.
- **Move.** Compare commit and tree hashes in code. If they are identical, the old verdict carries over. Run a post-decision check only if it names the rollback it could trigger.
- **Rigor after all.** After a credential compromise, re-verifying that the commits *are* the same commits is rigor. It takes one hash compare, not a full review.

## P8 wording pedantry

- **Case.** A registry swaps retired vocabulary words with no value changed. A closed verdict vocabulary is enforced by a linter. That is legitimate if machines parse those words, and pedantic if only people read them.
- **Move.** Block only when the wording changes a claim a reader would act on. Fix everything else inline.
- **Rigor after all.** "No worse" versus "non-inferior within a −0.20 margin", or "slightly better" versus "a positive estimate whose interval includes zero", change the claim. Corrections like those are right.

## P9 escalating in-domain calls

- **Case.** A plan says that if the third rater is unavailable, the dispute goes to a person "as a blocked input; no self-resolution". It sends several items to that person "regardless of outcome", and needs the same person's word for a routine maintenance window. A rule names one auditor model with no substitute, and that model is unavailable that day.
- **Move.** Decide inside the charter with a default and a revert path. A machinery outage reroutes; it never goes to a human. Settle a recurring policy call once as a standing delegation.
- **Rigor after all.** New model classes, policy instruments and walls are escalations a charter rightly requires.

## Neighbours

- `antibeaurocracy` F4-ceremony is the *wait* that a ceremony causes. P6 and P7 are the ceremony *itself* and whether it can change anything. When a card is blocked on a ceremony, classify the wait there and judge the check here.
- `frictionless` removes human steps. P9 removes in-domain decisions that were sent to a human and should never have reached one.
