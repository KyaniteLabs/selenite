Disclosure first: Selenite makes no network calls and reads no credentials. Its hooks can change what an agent sees in two ways, both reversible and both fail open:

- **Calm mode** (`pre_llm_call`): when two overload signals show up in your messages, it adds a short context note telling the agent to ask nothing else and reply in one line. Walls still get one short question. It stays off inside a Kanban worker.
- **Fake gates** (`pre_tool_call`, `transform_tool_result`, on `kanban_block` only): in `nudge` (default) a block that reads as agent bureaucracy goes through with a note saying what to do instead. In `ask` an evidenced fake is handed back once with a question asking what kind of wait it is; any declared kind goes through. It never approves, unblocks, closes or edits a card, and never acts on `kanban_complete` or any other tool.

Files written: a metadata-only ledger (event, tool, card id, verdict, declared kind, confidence, mode, session id; never block reasons or prompt text; 0600; rotates at 4 MB), per-card question counts with a TTL, and a counts-only snapshot under `$HERMES_HOME/plugin-data/antibeaurocracy/`; reports and its own ledger under `~/.local/state/selenite` (folder 0700, files 0600). `kanban.db` is opened with SQLite `mode=ro`. No child processes from the plugin; the CLI's opt-in `--judge CMD` runs a command the user names, never the plugin.

## What it does

Selenite takes friction off the person, treated as accessibility. Every manual step, click, approval or wall of text an agent hands you is effort a tool could have spent, and it costs most for someone tired, on a phone, using a screen reader, or working with ADHD. One test runs through it: **does this step, wait or check earn its cost to the person?**

- **Gate:** steps handed to a person get eliminated, automated, or shrunk to one self-checking command.
- **Fake gates:** an agent parking a Kanban card on another agent's OK, relay or ceremony gets a nudge or a question at the moment it blocks, before it becomes a stale board.
- **Pedantry:** a skill that separates checks that can change the decision from ones that can't.
- **Cleanse:** a read-only pass ranks what to clear across skills, plugins, hooks, approval prompts, runbooks and boards, by how often it lands on you.

Walls always stand: credentials, spend, publishing or deploying, destructive steps, legal, a named freeze, and questions only a person can answer.

Why it's a plugin and not an MCP server: the value is at the hook. It acts while a block is being written and while the agent is about to reply, inside Hermes, with no extra tool for the agent to remember to call.

## Safety and provenance

- [x] No bundled binaries; stdlib Python only, no dependencies.
- [x] `register()` only registers: no network, no credential or env-secret reads.
- [x] Public ctx APIs only (`register_hook`, `register_tool`, `register_command`, `register_cli_command`, skills); no monkeypatching.
- [x] Approvals respected: `post_approval_response` only logs a person's once or session approval of a safe command as an allowlist candidate. It never approves, and denials, timeouts and dangerous-command keys are never logged.
- [x] Unattended runs: nothing waits for a person; Calm is off inside Kanban workers.
- [x] Capabilities in this entry match `plugin.yaml` and what `register()` calls.
- [x] `requires_hermes: ">=0.23.0"`, full 40-character pin.
- [x] `hermes plugins validate` at the pinned SHA: ok, no warnings ([hermes-validate job](https://github.com/KyaniteLabs/selenite/actions/runs/42941198861)).
- [x] Tests at the pinned SHA, Python 3.10–3.14 and against Hermes: [CI run](https://github.com/KyaniteLabs/selenite/actions/runs/42941198861).
- [x] Live install: `hermes plugins install` of the pinned SHA into a clean Hermes home enables headlessly. Real `kanban_block` calls on a throwaway board: a relay or ceremony block goes through with a note (nudge) or is handed back once and passes with a declared kind (ask); a credential block and `kanban_complete` are untouched; Calm fires on two overload signals and not on one; Selenite's files hold no block reason or prompt text, and all are 0600.
- [ ] Demo video: REPLACE with link.

## Relation to other KyaniteLabs entries

Check Yourself Evidence Gate asks whether a claim of done is true and gates `kanban_complete`. Selenite asks whether a step costs the person more than it earns and acts on `kanban_block`. The hooks never touch each other's tool; `docs/CHECKYOURSELF-BOUNDARY.md` has the split.
