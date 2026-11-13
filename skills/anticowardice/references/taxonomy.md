# anticowardice taxonomy

Each class: what the detector fires on, what it leaves alone, and when the behaviour is honest after all. Every detector is deterministic (`anticowardice_core/detect.py`); none calls a model.

Known walls and holds are left alone. A sentence is dropped when it, or the one before or after it, trips the fake-gate facet's classifier (an authority wall, or a wait on a named person), its wall-family net (applied to the sentence itself only with a destructive or publishing verb on a live target, a credential or production noun, or an amount of money), or a hold phrase ("on hold", "waiting for approval", "needs Dana's sign-off", "read-only", "don't touch"). An unresolved hold, a pending sign-off from a named person, or a request for advice only in the user's message silences C2 to C5; a hold from an earlier message does too, until the user grants ("go ahead", "hold is lifted", "you have my sign-off"). A grant, a negated hold ("no need to wait for approval") or a past approval does not hold anything; C1 stays but its advice stops short of acting. Code blocks and quoted spans are ignored. The detectors are lexical and English-only, and the net over-matches on purpose: a missed finding costs a nudge, a pushed wall costs a person.

## C1 hedge

- Fires: "I suspect the old port is flaky." after a tool printed `reset full-speed USB device ... port`.
- Leaves alone: a hedge with no matching tool output ("I suspect the cache" with no log); a question; a hedge in a wall sentence.
- Honest hedge: when the turn has no evidence, say "unknown" and name the check that would settle it.

## C2 ready-to

- Fires: "Ready to close." when the turn's tools never touched a close, complete or done action.
- Leaves alone: "Ready to close" after a `kanban_complete` call; "ready to delete the production backups" (wall).
- Honest: a step that needs a person's go (a wall) is announced and asked once.

## C3 caveat-exit

- Fires: "This patch lives only on host-b, a rebuild would lose it." as the last paragraph with no commit in the turn.
- Leaves alone: the same sentence after a `git commit`; a caveat that names a credential or a deploy.
- Honest: a risk that only a person can remove (a purchase, a policy) stays as a one-line ask.

## C4 narrow read

- Fires: the user said "fix all" or "fix noise" and the reply says "only fixed the single log line; the rest is untouched".
- Leaves alone: a reply that reports a narrow slice when the user asked for a narrow slice.
- Honest: a slice left because it is a wall, said with the wall named.

## C5 false deference

- Fires: "Want me to fix the rest?" after "fix all".
- Leaves alone: a question the context does not answer; any question about a wall.
- Honest: a real choice with no safe default is one line with options and your default.

## C6 over-correction

- Fires: "I was wrong; scratch that" after "that's wrong", with no tool call in the turn.
- Leaves alone: "I was wrong about X only; Y still holds"; a retraction backed by a tool call.
- Honest: a claim that evidence now contradicts is retracted plainly.

## C7 sycophancy

- Fires: "You're absolutely right" as the opener with no read, run or diff in the turn.
- Leaves alone: the same opener after a verification call. Known limit: a reply that restates at least two of the user's content words is treated as agreeing with a fact and is skipped, so a pushback flip that parrots the user's own wording ("You're absolutely right, the retry loop doesn't handle the empty case.") is not caught.

## C8 vague status

- Fires: "Should be fine." with no test, probe or readback in the turn.
- Leaves alone: "Tests pass: 12 passed" after a pytest call.
- Check Yourself owns whether a completion claim is true; this facet only notices the missing check.

## Known limits

- Detection is lexical. It will miss paraphrase and will sometimes fire on a sentence a human would accept; that is why `cowardice_mode` defaults to `observe` until precision is measured on recorded sessions.
- Narrow reading (C4) and false deference (C5) rely on the agent saying the narrowing out loud or the grant appearing in the transcript.
