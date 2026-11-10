# Selenite

**Your agents stop making you do things they could have done.**

When an agent needs you for a login, a token, an approval or a click, it usually hands you a wall of steps and waits. Selenite gives agents the `frictionless` skill. It teaches them to remove that step, do it themselves, or shrink it to a single paste-ready command that checks its own result. It also notices when you're overloaded (cursing, typo bursts, "just do it") and switches the agent into a mode with no questions, a default it states, and a one-line reply. It learns from your transcripts which frictions recur, and proposes fixes to itself as pull requests you review.

## What's inside

| Path | What it is |
|---|---|
| `skills/frictionless/` | The skill, in the open [Agent Skills](https://agentskills.io) format. It works with any agent that loads `SKILL.md`: Claude Code, Codex, OpenCode, Hermes and others. |
| `__init__.py`, `plugin.yaml` | A Hermes plugin. It registers the skill, a `/frictionless` command, a `selenite_ledger` tool, and observe-only hooks. |
| `install.sh` | Links the skill into each agent it finds and the plugin into Hermes. It is idempotent and only creates links. |

## The four modes

- **Gate**: a step needs the human. Climb the ladder: eliminate the step, automate it, turn it into one idempotent self-checking command, and only then give guided steps.
- **Audit**: find friction in transcripts, permission prompts and runbooks. Rank it by frequency × time, and fix it with code first and prose last.
- **Calm**: overload signals appear. Fix the skipped rule, ask nothing, act, and reply in one line.
- **Evolve**: mine the transcripts, read the ledger, and write a proposal. A human merges the PR. Selenite never edits itself silently.

## Install

```bash
git clone <this repo> ~/src/selenite && ~/src/selenite/install.sh
```

Hermes picks up the plugin on its next gateway restart. Set `SELENITE_HOOKS=0` to keep the skill and command but turn the hooks off.

## Privacy

Everything Selenite learns stays on your machine, in `~/.local/state/selenite` (mode 0700). Reports hold only counts. Raw excerpts go to a private sample file that is never committed. Personal tuning lives in `~/.config/selenite/` (`profile.md`, `signals.txt`), outside the repo.

## Try it

```bash
python3 skills/frictionless/scripts/mine.py --days 30     # what's costing you time
python3 skills/frictionless/scripts/evolve.py             # what Selenite would change
```

## License

MIT
