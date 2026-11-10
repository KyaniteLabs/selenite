# Gate recipes

One-shot patterns for human steps that come up often. Every recipe ends with a check that prints PASS or FAIL.

## Paste a secret into a store without echoing it

```bash
read -rsp "Paste token: " T; printf %s "$T" | <store-cmd> --stdin; S=$?; unset T; [ $S -eq 0 ] && <verify-cmd> && echo PASS || echo FAIL
```

Swap `<store-cmd>` for the real sink, for example `gh secret set NAME`, `pass insert -m name` or `security add-generic-password`. The secret is cleared from the shell even when the store command fails. Never put the secret in argv.

## CLI login that opens the browser

Tell the human the one command, the account to choose, and the scopes. Then verify yourself:

```bash
gh auth login --web --scopes repo,workflow && gh auth status && echo PASS || echo FAIL
```

## Shared bot identity instead of per-agent logins

When several agents each need the same human login, propose one bot account with per-agent commit signatures (for example a `Co-Authored-By` or trailer naming the agent). One 2FA setup for the human, and attribution survives.

## 2FA and one-time codes

These can't be automated by design. Batch them: collect every step that needs a code into one sitting, say so up front ("you'll need your phone once, for three prompts"), and pre-run everything else.

## Remote shell on another machine

Give one command that does everything, including the SSH hop:

```bash
ssh -t <host> '<the whole thing> && echo PASS || echo FAIL'
```

## Dashboard-only settings

Give a deep link to the exact page, the exact control label, the value, and what the page shows when it's saved. If an API exists for the setting, use it instead and skip the human.
