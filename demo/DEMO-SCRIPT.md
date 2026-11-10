# Selenite demo: 60 seconds

TLDR: Open on the problem a person feels, a board full of agents waiting on each other. Show Selenite naming those waits at the moment they're written, then show it leave the real walls alone. Close on one line. Every command below was run at the pinned commit and printed what's shown.

Target length 45–70 s. Screen recording of a terminal plus the Hermes dashboard tab, voice-over, captions on (the captions are the script).

## Shots

| Time | Screen | Voice-over / caption |
|---|---|---|
| 0–6 s | A Kanban board with a column of blocked cards, all "waiting on" another agent. | "Your agents are waiting on each other. You're the one who untangles it." |
| 6–14 s | Terminal: `antibeaurocracy classify "Await the release agent to open the PR from my patch"` → `F2-relay (0.7) — Collapse the hop…` | "Selenite reads a wait the moment it's written. This one is a relay: the agent can do it itself." |
| 14–21 s | `antibeaurocracy classify "Need a reviewer agent to attest the evidence bundle"` → `F4-ceremony (0.7) — Drop the ceremony…` | "This one is ceremony. A second agent's sign-off adds a wait, not proof." |
| 21–29 s | `antibeaurocracy classify "waiting for the owner to rotate the API key"` → `credentials (0.9) — Escalate once to the human…` | "Real walls stand. Credentials, spend, publishing, legal: you get one short question, never a workaround." |
| 29–40 s | Hermes chat: an agent calls `kanban_block` with a relay reason; the tool result shows Selenite's nudge note. The card is not unblocked or edited. | "Inside Hermes it acts at the hook, with a note saying what to do instead. It never approves, unblocks or edits a card." |
| 40–50 s | Terminal: `python3 skills/frictionless/scripts/cleanse.py` → ranked list, top item highlighted. | "Cleanse sweeps your skills, hooks, approvals and boards, and ranks what lands on you most." |
| 50–58 s | Two messages in a row showing overload; the agent's reply is one line, no questions. | "When you're overloaded, Calm mode drops the agent to one line and no questions." |
| 58–65 s | Selenite name + "Does this step earn its cost to you?" + repo URL. | "Selenite. Friction is an accessibility problem. Install it once; it needs no cleansing." |

## Before recording

- Record on a throwaway `HERMES_HOME` with a seeded demo board. Never show a real board, card text, seat name, host, path or email.
- Run each `classify` line once off-camera and confirm the output matches the table. If it drifts, the table is wrong, not the take.
- Captions burned in and also uploaded as a sidecar `.srt`.

## Still needed

- [ ] Seeded demo board and `HERMES_HOME`.
- [ ] Banner (2:1) and 2–3 screenshots, after the design preflight in `docs/DESIGN-PREFLIGHT.md` is re-read for this pass.
- [ ] Recording, then the link in `catalog/PR-BODY.md`.
