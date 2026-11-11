# Selenite

<p align="center"><img src="branding/selenite-512.png" alt="Selenite icon: a thick raw satin-spar shard" width="160"></p>

**Selenite takes friction off the human: fewer manual steps, fewer clicks, fewer things to remember, read or decide.**

Friction here means every bit of effort a person spends that a tool could have spent: a login, a copied token, a trip through a dashboard, a command to remember, an approval clicked for the fortieth time, a wall of text to read, a question to answer. That makes it an accessibility problem as much as an agent problem. Every step removed helps the person who is tired, overloaded, on a phone, using a screen reader or keyboard only, or working with ADHD or another disability.

People keep a selenite wand next to their other crystals to clear and recharge them. Selenite does that for your agent stack. It sweeps your skills, plugins, hooks, approval prompts, runbooks and Kanban boards for whatever keeps handing work back to you, ranks it by how often it lands on you, and drafts the fix. When a human step really can't be removed, it shrinks it to one paste-ready command that checks its own result. When your messages show overload, it switches the agent to no questions and one-line replies.

One test runs through all of it: **does this step, wait or check earn its cost to the person?** Selenite applies it in three facets:

- **Gate** (`frictionless` skill): steps handed to a person, such as logins, approvals, copied tokens and manual runbook steps.
- **Fake gates** (`antibeaurocracy` skill): one agent parking work on another for a reason that isn't real. Those waits pile up into a stale board a person has to untangle.
- **Pedantry** (`antipedantry` skill): checks that can't change the decision but still delay or escalate it.

Walls always stand: credentials, spend, publishing or deploying, destructive steps, legal, a named freeze, and questions only a person can answer. Selenite asks those once, as a decision, and never routes around them.

**Selenite needs no cleansing.** The stone clears others and is never cleared itself. Selenite holds to that as a requirement: no upkeep after install, state that trims itself, and a CI gate that keeps its own skill clean, so it never shows up on your list.

## What's inside

| Path | What it is |
|---|---|
| `skills/` | The three facet skills (`frictionless`, `antibeaurocracy`, `antipedantry`) in the open [Agent Skills](https://agentskills.io) format. They work with any agent that loads `SKILL.md`: Claude Code, Codex, OpenCode, Hermes and others. |
| `antibeaurocracy_core/`, `bin/` | The fake-gate classifier and board audit: stdlib Python 3.10+, no dependencies, and the `antibeaurocracy` CLI. |
| `__init__.py`, `plugin.yaml` | A Hermes plugin. It registers the three skills, the `/frictionless`, `/antibeaurocracy` and `/fake-gate` commands, the `selenite_ledger`, `bureaucracy_classify` and `bureaucracy_audit` tools, and eight hooks. |
| `install.sh` | Links the skills into each agent it finds and the CLI into `~/.local/bin`, creates the state folder (0700) and checks the ledger works. Add `--hermes` to also link the plugin and enable it in Hermes. Idempotent; it never overwrites a real file or folder, and warns when a real folder hides a skill link. A read-only target (an agent seat, a managed Mac, a container) is skipped, not fatal: every target is attempted and the last line counts linked, skipped and failed. `--no-enable` links the plugin but leaves `hermes plugins enable` to you. |
| `desktop/` | The Hermes Desktop page, status chip and Kanban badges (`plugin.js`), plus the Chakra Petch subsets it embeds. |
| `dashboard/` | The web dashboard tab and its backend routes (`plugin_api.py`, plus `fake_gates_api.py` for the fake-gate card), served by Hermes under `/api/plugins/selenite/`. |
| `assets/` | The icon concept SVG and the Chakra Petch font license (OFL). |
| `branding/`, `icon.png` | The approved icon render and its sizes. |
| `docs/` | The design system, the design preflight receipt, `MERGE-INTENT.md` (why the three facets are one product) and `CHECKYOURSELF-BOUNDARY.md` (where Selenite stops and Check Yourself starts). |
| `CHANGELOG.md`, `NOTICE` | Release notes, and the attribution for the merged antibeaurocracy and antipedantry code. |
| `tests/` | Unit tests for the scripts, the plugin hooks, the backend routes, and the needs-no-cleansing requirement. |
| `tools/` | `embed-fonts.py`, which rebuilds the font subsets embedded in `desktop/plugin.js`. |

One product: **Selenite** is the product, and its three skills are its facets. The names `antibeaurocracy` and `bureaucracy_*` are kept as they were so existing installs and scripts keep working.

## The four modes

- **Cleanse**: sweep the other stones (skills, plugins, hooks, approvals, gates, runbooks, fake gates on the boards), rank what to clear by how often it interrupts you, and clear the top one with a reviewable change. Code first, prose last.
- **Gate**: a step needs you. Eliminate it, automate it, or shrink it to one idempotent, self-checking command that works by keyboard and screen reader. Guided steps come last.
- **Calm**: two overload signals show up. The agent fixes the rule it skipped, asks nothing else, acts, and replies in one line. Walls still stand and still get one short question. Calm stays off inside a Kanban worker, where no person is reading.
- **Evolve** (optional): sharpen Selenite. It mines your transcripts, reads its ledger and the latest cleanse, and writes a proposal for better signals. Skip it and nothing degrades.

## Install

```bash
git clone <this repo> ~/src/selenite && ~/src/selenite/install.sh            # the skill, for every agent found
~/src/selenite/install.sh --hermes                                          # and the Hermes plugin
```

Hermes picks up the plugin on its next gateway restart. In Hermes, the `hooks` setting (or `SELENITE_HOOKS=0`) turns every hook off and keeps everything else. If you ran the standalone antibeaurocracy plugin before, disable it: running both doubles the fake-gate hooks, and the installer warns when it finds one.

One Selenite per machine: if `~/.local/share/selenite` or another Hermes home already has the plugin, `--hermes` reuses that copy instead of adding a second checkout of the same plugin name, which Hermes refuses to admit (`Two workspace members are both named 'selenite'`).

In a sandbox or a seat with a read-only home, the installer skips the folders it cannot write and still links the rest. `--hermes` ends with `hermes plugins enable selenite`; on a source checkout that command may first finish a pending Hermes update and rebuild its desktop app, so pass `--no-enable` when a caller has its own timeout and run the printed command yourself.

Fake-gate settings live under `plugins.entries.selenite.settings`: `fake_gate_mode` (`observe`, `nudge` by default, or `ask`), `max_refusals`, `refusal_ttl_hours`, `min_confidence`, `extra_seats`, `extra_ceremony`, `doctrine_section`, `fake_gate_ledger` and `snapshot_minutes`. `plugin.yaml` says what each does. Start in `observe` or `nudge` and read the ledger before trying `ask`. The CLI and the dashboard card read the same `extra_seats`, `extra_ceremony` and `min_confidence`; `antibeaurocracy audit --seat NAME` adds to the configured seats.

The plugin also offers a **weekly-audit** automation blueprint in Hermes: once a week, counts only, it reports blocked vs running cards, the evidenced fake share and any shared cause blocking two or more cards. It never names cards or people and never changes a card.

## Try it

```bash
python3 skills/frictionless/scripts/cleanse.py              # what to clear next, across your stack
python3 skills/frictionless/scripts/mine.py --days 30       # where your sessions cost you time
python3 skills/frictionless/scripts/evolve.py               # what Selenite would change about itself

antibeaurocracy classify "Await the release agent to open the PR from my patch"   # is this wait real?
antibeaurocracy audit             # read-only: kanban boards + the rule files your agents load
antibeaurocracy audit --counts    # numbers only, nothing from the cards
antibeaurocracy audit --judge "llm -m some-model"   # optional second opinion, see below
```

`--judge CMD` is off by default and exists only in the CLI audit; the plugin's hooks never call a model. It sends the reason of each card the classifier calls fake (oldest 20, `--judge-max`) to a command you pick, on stdin, without a shell, and lists the cards where its one-word answer disagrees. The classifier's verdict stays the verdict. Use it only with a command you trust with your card text.

## Disclosure

- **Reads:**
  - Your agent homes, when you run `cleanse.py` or the tool's `cleanse` action. That covers skill folders, the Hermes plugins folder, Claude Code `settings.json` hook commands, any runbook path you pass, and the fake-gate ledger. `mine.py` reads your own messages in Claude Code (`~/.claude/projects`), Codex (`~/.codex/sessions`) and Hermes (`$HERMES_HOME/state.db`, opened read-only), plus any `--path`.
  - `kanban.db` files under `$HERMES_HOME`, opened with SQLite `mode=ro`, for the fake-gate audit, tool and dashboard card. The CLI audit also scans every `~/.hermes*` directory.
  - The CLI audit (not the plugin hooks or tools) reads the agent rule files it finds, such as `~/.claude/CLAUDE.md`, `~/AGENTS.md`, `~/.agents/rules/*.md` and each Hermes home's `SOUL.md`, and prints up to eight example gate lines from each. Selenite's own skills are skipped. Use `--no-rules` to skip this, or `--counts` for numbers only.
- **Writes:**
  - The ledger, reports and proposals in the state folder (folder 0700, files 0600): `$SELENITE_STATE`, else `$XDG_STATE_HOME/selenite`, else `$HERMES_HOME/plugin-data/selenite`, else `~/.local/state/selenite`. Each `cleanse.py` run writes a report there and one ledger row with its finding count; if no folder takes the write (a read-only home, the normal case in an agent seat) it prints one line saying so and still prints the findings. Ledger notes are redacted before they are written.
  - `$HERMES_HOME/plugin-data/antibeaurocracy/`: `ledger.jsonl` (0600, rotating at 4 MB: event, tool, card id, verdict, declared kind, confidence, mode and session id, never reason or prompt text), `refusals.json` (per-card question counts in `ask` mode, expiring after `refusal_ttl_hours`) and `snapshot.json` (counts only).
  - The installer creates symlinks (the skills in each agent's skills folder, the CLI in `~/.local/bin`, and with `--hermes` the plugin in `$HERMES_HOME/plugins`) and the state folder. A target it cannot write is skipped and counted, never fatal. With `--hermes` it also runs `hermes plugins enable selenite`, which changes Hermes's config; `--no-enable` leaves that command to you.
  - Selenite never edits another tool, card or rule file. Every fix is a proposal or a change you review.
- **Changes agent behaviour:**
  - In Calm mode, when two overload signals appear, `pre_llm_call` adds a short context note telling the agent to ask nothing and reply in one line.
  - In `fake_gate_mode` `nudge` (the default), a `kanban_block` that reads as agent bureaucracy goes through with a note added to the tool result saying what to do instead.
  - In `ask`, an evidenced fake block is handed back once with a question: what kind of wait is it? Any declared kind goes through. Text with a wall word is only nudged, never asked. It asks at most `max_refusals` times per card, and any error fails open.
  - Approvals are never skipped, and no card is ever unblocked, closed or edited.
- **System prompt:** unchanged unless you turn on `doctrine_section`.
- **Hooks:** besides the above, they only log an event. An approval is logged only when a person granted it once or for a session on a safe command, as an allowlist candidate. Denials, timeouts, the smart approver's own decisions, payment and MCP prompts, and Hermes's own dangerous-command keys (recursive delete, force push, SQL drop and the like) are never logged. Choosing "always" marks it fixed; a later prompt for the same key reopens it.
- **Network:** none from the plugin. The desktop app and dashboard read through your own Hermes gateway. The CLI's opt-in `--judge` runs whatever command you give it, which may.
- **Env:** `SELENITE_STATE`, `SELENITE_HOME`, `SELENITE_HOOKS`, `SELENITE_AGENT` (the agent name on ledger rows you add by hand), `HERMES_HOME`, and inside a Kanban worker `HERMES_KANBAN_TASK` and `HERMES_KANBAN_BOARD` to key refusals per card.
- **Credentials:** none.

## Privacy

What Selenite learns stays on your machine. Reports hold counts and category names, never a host name. Miner samples quote your own messages, so they are redacted (emails, IPs, credentials in URLs and headers, key=value secrets, known token prefixes, long tokens, your home path), kept at 0600, and only the newest three are kept. The ledger stores task ids, never Kanban block reasons. It rotates at 4 MB. Personal tuning lives in `~/.config/selenite/` (`signals.txt`, `profile.md`), outside the repo. In shared chats, set `calm_senders` so only your own messages count toward Calm.

## Tests

```bash
python3 -m pip install pytest fastapi httpx && python3 -m pytest -q
```

## License

MIT. The merged antibeaurocracy and antipedantry code keeps its own attribution in `NOTICE`. Selenite is an independent project by KyaniteLabs and is not endorsed by Nous Research.
