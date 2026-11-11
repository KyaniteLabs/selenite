# Changelog

## 0.5.0 (unreleased)

### Install acceptance fixes (2026-11-10)

- **Headless install stays enabled:** `pyproject.toml` no longer carries a `[build-system]` table.
  Hermes read it as "installs Python packages" and stopped a non-interactive
  `hermes plugins install --enable` at a dependency-consent question, leaving Selenite disabled
  although it has no dependencies. `pip install .` still gives the `antibeaurocracy` command.
- **Settings on a real config:** without PyYAML or ruamel, the stdlib reader now parses only the
  top-level `plugins:` block. A list of mappings elsewhere (`custom_providers`) used to make every
  setting unreadable and print a warning on each CLI run.
- **Lock file mode:** the ask-mode refusal store's lock is created 0600 like every other file
  Selenite writes; it used to follow the umask (0664).

### Dogfood fixes (2026-11-10)

- **Packaging in a read-only seat:** the defects that only show up in the environment Selenite is
  built for. `cleanse.py` no longer dies with `OSError: [Errno 30] Read-only file system` after
  computing its findings: the state folder is `$SELENITE_STATE`, else `$XDG_STATE_HOME/selenite`,
  else `$HERMES_HOME/plugin-data/selenite`, else `~/.local/state/selenite`; every write falls
  through that list, and when none takes it one line says so and the findings still print (exit 0).
  The ledger treats the same case as "quietly skip the row" instead of failing the agent's turn.
  `install.sh` no longer aborts at the first read-only target: a read-only target is skipped, a real
  failure is recorded, every other target is still attempted, `linked / skipped / failed` is the
  last line, and only a real failure exits non-zero. `--hermes` reuses the Selenite this machine
  already loads (`~/.local/share/selenite` or another Hermes home) and repoints a link at a second
  checkout, because two sources with one plugin name are refused by Hermes admission. The
  `hermes plugins enable` step is last, never fatal, and `--no-enable` skips it: on a source
  checkout that command may first complete a code update and a desktop rebuild.
- **classify.py:** catalog/marketplace/store/registry submissions are now publishing walls
  ("Needs Simon to approve the catalog entry" is a WALL, not F6), and the infinitive form after a
  role ("needs the CEO to approve", "waiting on the owner to sign off") reads as a person's
  approval. Proper names are deliberately still not matched (product names are not people).

Selenite, antibeaurocracy and antipedantry are now one product, Selenite, with three facets of one test: does this step, wait or check earn its cost to the person? See `docs/MERGE-INTENT.md` for the intent and what the merge surfaced.

- **One plugin:** the fake-gate hooks, tools, commands and dashboard card now load from the `selenite` Hermes plugin. Disable a standalone antibeaurocracy plugin, or its hooks run twice.
- **Settings renamed:** `mode` is now `fake_gate_mode` and `ledger` is now `fake_gate_ledger`, under `plugins.entries.selenite.settings`. Selenite's `hooks` switch and `SELENITE_HOOKS=0` turn the fake-gate hooks off too.
- **One observer for blocked cards:** `kanban_task_blocked` classifies once. A wait that lands on a person (a wall or a human question) is logged on Selenite's ledger; an approval an agent asks of another agent no longer counts as a human step.
- **Cleanse reads the boards:** the fake-gate stone counts distinct cards with evidenced fake verdicts (confidence 0.6 or more) from both ledger files.
- **Bounded and loud:** the fake-gate ledger rotates at 4 MB and is written 0600. The rules audit reports a file it can't read instead of skipping it, and skips Selenite's own skills. The dashboard caches the board audit for 30 seconds and logs config or ledger read failures.
- **One list of walls:** `WALLS` in `classify.py` feeds Calm, the doctrine, the nudge, the question and the skill text, and a test holds them together. A capability gap and rotated credentials count as walls.
- **Approvals:** only a person's once or session approval of a safe command is logged, as an allowlist candidate. Denials, timeouts, the smart approver, payment and MCP prompts, and Hermes's dangerous-command keys are not. "Always" marks the key fixed; a later prompt reopens it. Long keys truncate to one length. Calm stays off inside a Kanban worker.
- **Blocked cards:** a declared kind decides the route first, and the kind an agent declared in `pre_tool_call` carries over to `kanban_task_blocked`. A block Hermes rejects no longer hides the next real one. Any status change clears the badge, not only completion.
- **Cleanse:** a fake-gate card counts by its latest event, so an ask or a declared kind clears it and a later fake block reopens it. Runbook lines that only mention 2FA, OTP or friction are not counted as steps. Each run writes a report and one ledger row.
- **Evolve:** a category's silence counts only in cycles that measured it, a damaged state file resets, notes are redacted, and the proposal leaves opening a PR to the human.
- **Settings without private imports:** the plugin, the CLI and the dashboard read `extra_seats`, `extra_ceremony`, `min_confidence` and `fake_gate_mode` through `settings.py`, from `$HERMES_HOME/config.yaml` outside Hermes. A bad config is reported, not hidden, and a host with no YAML library reads it with a small stdlib reader. `audit --seat` adds to the configured seats. The stored block kind is read from the documented Kanban DB layout. `hermes plugins validate` passes with no warnings, and both CI workflows now fail on any warning.
- **Ledger redaction** covers more secret shapes; plain words are left alone. `install.sh` warns when a real folder hides a skill link.
- **Check Yourself boundary:** `docs/CHECKYOURSELF-BOUNDARY.md` splits the two products by question (truth of a completion claim vs cost of the process to the person). Tests hold Selenite off `kanban_complete` and keep a missing-evidence wait from being nudged or asked.
- **Imported from** antibeaurocracy main @a564f2c, whose tree is identical to 0.3.0 below.

## 0.3.0 (antibeaurocracy)

The plugin now asks instead of refusing. A regex will always miss some phrasing of a real wall, so the mode that pushes back on a block no longer rules on it.

- **`ask` mode replaces `enforce`:** an evidenced fake (any of F1–F5) with no declared `kind` is handed back once with a question listing the legitimate kinds. Whatever kind the agent declares goes through and is ledgered as a `declared` event next to the regex verdict. Text with any wall-family word is only nudged. `max_refusals` now defaults to 1. A setting of `enforce` is read as `ask`.
- **Ledger events:** `refused` is now `asked`; `declared` is new. Anything that counts fakes, such as Selenite's cleanse, should count only `block_attempt` and `blocked_observed` rows, so one block isn't counted twice.
- **`audit --judge CMD`:** an opt-in second opinion from any command you choose, run without a shell over the oldest fake cards. Disagreements are listed; the regex verdict stands. CLI only, refused with `--counts`, never called by the hooks.
- **Scope:** Selenite owned friction that lands on a human across the whole stack; both skills and the README said so. (0.5.0 merged the two.)
- **Sibling skill:** `antipedantry` (rigor that can't change a decision) ships in the same repo.

## 0.2.1 (unreleased)

Three more review rounds tightened the classifier. Each round fixed the phrasings it was shown and broke a neighbouring one, so enforce mode no longer trusts the classifier alone: it is marked experimental and refuses only when the full text has no wall-family word at all.

- **HUMAN:** a role counts as a person's authority only when it is the source of the wait ("from the CEO", "per the owner", "the founder's OK", "the CEO must countersign"). A bare noun ("waiting for the client to connect", "for the board update") or an agent named after a role ("the CEO agent", "the CEO's agent") no longer counts. A person's wait stays HUMAN when a fault is also mentioned. `kind=capability` and `kind=transient` are MACHINERY.
- **Walls:** costs match any amount ("roughly 3000", "3k", "$40/month"). A bare count per month does not ("retries 3 per month"); three or more digits do. A stated absence is still a wall ("no budget approval yet", "no API key") unless the text says it isn't needed ("no payment needed"). Negation applies only on the same line. "e-stop" matches. Added terraform, kubectl and helm, force pushes, "delete everything" and cluster resources. An infra command reported as failing, with no gate phrase, is MACHINERY; with one, it stays a wall. Only an upper-case HOLD or PARKED is parking evidence.
- **Enforce (experimental):** refuses only F2-relay and F4-ceremony, and only when the full reason has no wall-family word (money, prod, deletion, credentials, publishing, legal, freezes, a person's role); everything else is nudged. A refusal TTL of 0 or less falls back to the default and one under an hour is raised to an hour, so counts outlive retries and enforce fails open after `max_refusals`. Any error in the hook fails open. A board argument takes precedence over the environment.
- **Robustness:** numeric settings are clamped, and malformed refusal or ledger files are tolerated. The refusal store uses one lock per process with a bounded wait. Reasons over 4000 characters are classified on their first and last 2000, so a hook can't time out and a wall at the end still counts; the enforce net reads the full text.
- **Ledger:** a block the gate let through isn't recorded a second time by the lifecycle hook. The dedupe is keyed on task id only, and refused calls are excluded.
- **Dashboard:** `/overview` works again (the import was broken), returns counts only and shows no assignees. Junk ledger lines and bad bytes are skipped.
- **Vocabulary:** org-specific terms were removed from the classifier and tests. The classifier still ships generic gate words such as "relay", "attestation" and "ledger row", since those are the patterns it detects. The audit's gate-word list dropped "charter" and "admission".
- **Docs:** the taxonomy, SKILL.md check order and README now match the code, and a test checks the order.

## 0.2.0 (unreleased)

A full review found the classifier and plugin overconfident. This release makes them honest.

- **Walls:** verb-stem matching for deleting data, spending money, sending email or posts, deploying to prod, merging to main, rewriting history and legal sign-off. Negated wall words ("no spend involved") no longer count. No action text claims a step is safe.
- **New HUMAN class:** questions for a person and `kind=needs_input` are never treated as agent bureaucracy, and enforce mode never refuses them.
- **Audit counts:** a card is fake only with a matched phrase and enough confidence. Unevidenced defaults are "unclear"; created-blocked and dispatcher auto-blocked cards get their own buckets; boards that can't be read are reported.
- **Privacy:** agent names are not built in. Teams add their own agent names with `extra_seats` / `--seat`. The tool, blueprint, snapshot and remote chat surfaces are counts only.
- **Enforce mode:** refusal counts persist per card on disk with a TTL, so worker restarts can't cause endless refusals. The gate logic is an explicit, tested state table (`antibeaurocracy_core/gates.py`).
- **Hooks:** dropped the `kanban_create` gate; added an observe-only `kanban_task_blocked` listener. Nudges are keyed per tool call and expire.
- **Doctrine section:** off by default.
- **Packaging:** `pip install .` gives the `antibeaurocracy` command; CI on Forgejo and GitHub (Python 3.10–3.14, pinned actions).

## 0.1.0

First version: classifier, read-only audit, Hermes plugin, skill and dashboard tab.
