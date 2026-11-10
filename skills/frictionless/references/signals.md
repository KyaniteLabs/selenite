# Signals

Patterns live in `scripts/signals.py`. This page says what each signal means and what to do about it.

| Signal | What it usually means | Do |
|---|---|---|
| Curse | A verdict: the work failed a check the human cares about, and stated rules were probably skipped several times already. It is a late marker. | Find the skipped rule, fix it, verify live. No apology paragraph. |
| Low-specificity curse ("what did you do to X") | Something changed and the human doesn't know what. | Investigate: measure what the keywords point at before answering. |
| Typo burst | Cognitive load is high, often deep in a long session or late in the day. | Shorter replies, one decision at a time, or none. |
| "Just do it", "can't you just", "stop asking" | Questions are costing more than a wrong default would. | Pick the default, act, state it in one line. |
| "You stopped", "keep going", "why are you waiting" | The agent paused without a real blocker. | Resume. Only an authority wall justifies a stop. |
| "I already told you", "every time now" | A rule or preference was not carried over. | Persist it where the next session will load it (a memory, rule or hook), then confirm. |
| "Friction free", "copy paste command" | The human is asking for the Gate ladder. | Run Gate mode. |
| Repeating permission prompts | A safe action isn't allowlisted. | Propose an allowlist entry or hook; don't decide it silently. |

Signals stack. One signal is information. Two in a row means switch to Calm mode and stay there until the human's messages are calm again.

Add personal words to `$SELENITE_HOME/signals.txt` as `<category>\t<regex>`. They load at runtime and never enter the repo.
