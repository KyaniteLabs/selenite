# Selenite

**Your agents stop making you do things they could have done.**

When an agent needs you for a login, a token, an approval or a click, it usually hands you a wall of steps and waits. Selenite gives agents the `frictionless` skill. It teaches them to remove that step, do it themselves, or shrink it to a single paste-ready command that checks its own result. It also notices when you're overloaded (cursing, typo bursts, "just do it") and switches the agent into a mode with no questions, a default it states, and a one-line reply. It learns from your transcripts which frictions recur, and proposes fixes to itself as pull requests you review.

## What's inside

| Path | What it is |
|---|---|
| `skills/frictionless/` | The skill, in the open [Agent Skills](https://agentskills.io) format. It works with any agent that loads `SKILL.md`: Claude Code, Codex, OpenCode, Hermes and others. |
| `__init__.py`, `plugin.yaml` | A Hermes plugin. It registers the skill, a `/frictionless` command, a `selenite_ledger` tool, and observe-only hooks. |
| `install.sh` | Links the skill into each agent it finds and the plugin into Hermes. It is idempotent and only creates links. |
| `desktop/` | The Hermes Desktop page, status chip and Kanban badges (`plugin.js`), plus the Chakra Petch subsets it embeds. |
| `dashboard/` | The web dashboard tab and its backend routes (`plugin_api.py`), served by Hermes under `/api/plugins/selenite/`. |
| `assets/` | The icon and the Chakra Petch font license (OFL). |
| `docs/` | The design system and the design preflight receipt. |
| `tools/` | `embed-fonts.py`, which rebuilds the font subsets embedded in `desktop/plugin.js`. |

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

## What it reads and writes

- **Reads**, only when you run `mine.py`: your user messages in Claude Code (`~/.claude/projects`), Codex (`~/.codex/sessions`) and Hermes (`~/.hermes/state.db`, opened read-only), plus any path you pass with `--path`.
- **Hooks**: `pre_llm_call`, `pre_approval_request`, `post_approval_response` and `kanban_task_blocked`. They only log an event or add context. They never block, approve or edit anything.
- **Writes** only to `~/.local/state/selenite`.
- **Network**: none. The desktop app reads the ledger through your own Hermes gateway.

## Try it

```bash
python3 skills/frictionless/scripts/mine.py --days 30     # what's costing you time
python3 skills/frictionless/scripts/evolve.py             # what Selenite would change
```

## License

MIT
