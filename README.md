# Selenite

**Selenite takes friction off the human: fewer manual steps, fewer clicks, fewer things to remember, read or decide.**

Friction here means every bit of effort a person spends that a tool could have spent: a login, a copied token, a trip through a dashboard, a command to remember, an approval clicked for the fortieth time, a wall of text to read, a question to answer. That makes it an accessibility problem as much as an agent problem. Every step removed helps the person who is tired, overloaded, on a phone, using a screen reader or keyboard only, or working with ADHD or another disability.

People keep a selenite wand next to their other crystals to clear and recharge them. Selenite does that for your agent stack. It sweeps your skills, plugins, hooks, approval prompts and runbooks for whatever keeps handing work back to you, ranks it by how often it lands on you, and drafts the fix. When a human step really can't be removed, it shrinks it to one paste-ready command that checks its own result. When your messages show overload, it switches the agent to no questions and one-line replies.

**Selenite needs no cleansing.** The stone clears others and is never cleared itself. Selenite holds to that as a requirement: no upkeep after install, state that trims itself, and a CI gate that keeps its own skill clean, so it never shows up on your list.

## What's inside

| Path | What it is |
|---|---|
| `skills/frictionless/` | The skill, in the open [Agent Skills](https://agentskills.io) format. It works with any agent that loads `SKILL.md`: Claude Code, Codex, OpenCode, Hermes and others. |
| `__init__.py`, `plugin.yaml` | A Hermes plugin. It registers the skill, a `/frictionless` command, the `selenite_ledger` tool and observe-only hooks. |
| `install.sh` | Links the skill into each agent it finds. Add `--hermes` to link and enable the Hermes plugin. Idempotent; it only creates links. |
| `desktop/` | The Hermes Desktop page, status chip and Kanban badges (`plugin.js`), plus the Chakra Petch subsets it embeds. |
| `dashboard/` | The web dashboard tab and its backend routes (`plugin_api.py`), served by Hermes under `/api/plugins/selenite/`. |
| `assets/` | The icon concept and the Chakra Petch font license (OFL). |
| `docs/` | The design system and the design preflight receipt. |
| `tests/` | Unit tests for the scripts, the plugin hooks, the backend routes, and the needs-no-cleansing requirement. |
| `tools/` | `embed-fonts.py`, which rebuilds the font subsets embedded in `desktop/plugin.js`. |

One product, one skill: **Selenite** is the product, `frictionless` is its skill, and `selenite_ledger` is its tool.

## The four modes

- **Cleanse**: sweep the other stones (skills, plugins, hooks, approvals, gates, runbooks, peer products), rank what to clear by how often it interrupts you, and clear the top one with a reviewable change. Code first, prose last.
- **Gate**: a step needs you. Eliminate it, automate it, or shrink it to one idempotent, self-checking command that works by keyboard and screen reader. Guided steps come last.
- **Calm**: two overload signals show up. The agent fixes the rule it skipped, asks nothing, acts, and replies in one line. Authority walls still stand.
- **Evolve** (optional): sharpen Selenite. It mines your transcripts, reads its ledger and the latest cleanse, and writes a proposal for better signals. Skip it and nothing degrades.

## Install

```bash
git clone <this repo> ~/src/selenite && ~/src/selenite/install.sh            # the skill, for every agent found
~/src/selenite/install.sh --hermes                                          # and the Hermes plugin
```

Hermes picks up the plugin on its next gateway restart. In Hermes, the `hooks` setting (or `SELENITE_HOOKS=0`) turns the hooks off and keeps everything else.

## Try it

```bash
python3 skills/frictionless/scripts/cleanse.py              # what to clear next, across your stack
python3 skills/frictionless/scripts/mine.py --days 30       # where your sessions cost you time
python3 skills/frictionless/scripts/evolve.py               # what Selenite would change about itself
```

## Disclosure

- **Reads:** your agent homes, when you run `cleanse.py` or the tool's `cleanse` action. That covers skill folders, the Hermes plugins folder, Claude Code `settings.json` hook commands, and any runbook path you pass. It also reads antibeaurocracy's metadata ledger when one exists. `mine.py` reads your own messages in Claude Code (`~/.claude/projects`), Codex (`~/.codex/sessions`) and Hermes (`$HERMES_HOME/state.db`, opened read-only), plus any `--path`.
- **Writes:** the ledger, reports and proposals in `~/.local/state/selenite` (folder 0700, files 0600). The installer also creates symlinks: the skill in each agent's skills folder, and with `--hermes` the plugin in `$HERMES_HOME/plugins`. Selenite never edits another tool. Every fix is a proposal or a change you review.
- **Changes agent behaviour:** yes, in Calm mode. When two overload signals appear, `pre_llm_call` adds a short context note telling the agent to ask nothing and reply in one line. Nothing else changes, and approvals are never skipped.
- **System prompt:** not modified.
- **Hooks:** they only log an event or add that Calm note. They never block, approve or edit anything. Approval rows count only prompts a human saw: the smart approver's own decisions and folded follower prompts are skipped.
- **Network:** none. The desktop app and dashboard read the ledger through your own Hermes gateway.
- **Env:** `SELENITE_STATE`, `SELENITE_HOME`, `SELENITE_HOOKS`, `HERMES_HOME`.
- **Credentials:** none.

## Privacy

What Selenite learns stays on your machine. Reports hold counts and category names, never a host name. Miner samples quote your own messages, so they are redacted (emails, IPs, credentials in URLs, long tokens, your home path), kept at 0600, and only the newest three are kept. The ledger stores task ids, never Kanban block reasons. It rotates at 4 MB. Personal tuning lives in `~/.config/selenite/` (`signals.txt`, `profile.md`), outside the repo. In shared chats, set `calm_senders` so only your own messages count toward Calm.

## Tests

```bash
python3 -m pip install pytest fastapi httpx && python3 -m pytest -q
```

## License

MIT
