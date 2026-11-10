#!/usr/bin/env sh
# Selenite installer. Links its three skills (frictionless, antibeaurocracy,
# antipedantry) into each agent harness it finds and the `antibeaurocracy` CLI
# into ~/.local/bin; with --hermes it also links and enables the Hermes plugin.
#   ./install.sh             link the skills and CLI wherever a harness exists
#   ./install.sh --hermes    also install the Hermes plugin (it registers all three skills itself)
#   ./install.sh --dry-run   show what would be linked
# Idempotent. It creates symlinks and the state folder, and with --hermes runs
# `hermes plugins enable selenite`. It never overwrites a real file or folder.
set -eu
ROOT=$(cd "$(dirname "$0")" && pwd)
SKILL="$ROOT/skills/frictionless"
DRY=0; HERMES=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --hermes) HERMES=1 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

FAILED=0
link() {  # link <target> <link-path>
  if [ -L "$2" ] && [ "$(readlink -f "$2")" = "$(readlink -f "$1")" ]; then echo "ok    $2"; return; fi
  if [ -d "$2" ] && [ ! -L "$2" ]; then
    echo "warn  $2 is a real folder, not a link, so that agent loads it instead of Selenite."
    echo "      Move it aside and run install.sh again."; return
  fi
  if [ -e "$2" ] || [ -L "$2" ]; then echo "skip  $2 (exists, not a Selenite link)"; return; fi
  if [ "$DRY" = 1 ]; then echo "would $2 -> $1"; return; fi
  # One unwritable agent dir must not abort the rest of the install (a read-only
  # ~/.claude on a locked-down host once stopped every later link silently).
  if mkdir -p "$(dirname "$2")" 2>/dev/null && ln -s "$1" "$2" 2>/dev/null; then
    echo "link  $2"
  else
    echo "FAIL  $2 ($(dirname "$2") not writable or link refused)" >&2
    FAILED=$((FAILED + 1))
  fi
}

# Agent Skills-format homes. Hermes is not listed: its plugin registers the skills,
# so linking them into the Hermes skills folder as well would load them twice.
for NAME in frictionless antibeaurocracy antipedantry; do
  for H in .claude .agents .codex .config/opencode; do   # Claude Code, any agentskills reader, Codex, OpenCode
    [ -d "$HOME/$H" ] && link "$ROOT/skills/$NAME" "$HOME/$H/skills/$NAME"
  done
done
link "$ROOT/bin/antibeaurocracy" "$HOME/.local/bin/antibeaurocracy"   # the fake-gate CLI, for any shell
true  # a missing harness is not an error
found=0; for d in .claude .agents .codex .config/opencode; do [ -d "$HOME/$d" ] && found=1; done
[ "$found" = 1 ] || [ "$HERMES" = 1 ] || echo "No agent home found (~/.claude, ~/.agents, ~/.codex, ~/.config/opencode), so nothing was linked."

if [ "$HERMES" = 1 ]; then
  HH=${HERMES_HOME:-$HOME/.hermes}
  link "$ROOT" "$HH/plugins/selenite"
  # Selenite now carries the fake-gate facet. A standalone antibeaurocracy plugin would run the same hooks twice.
  if [ -e "$HH/plugins/antibeaurocracy" ] || [ -L "$HH/plugins/antibeaurocracy" ]; then
    echo "warn  $HH/plugins/antibeaurocracy is still installed; Selenite includes it now."
    echo "      Disable it so its hooks don't run twice: hermes plugins disable antibeaurocracy"
  fi
  if [ "$DRY" = 0 ] && command -v hermes >/dev/null 2>&1; then
    HERMES_HOME=$HH hermes plugins enable selenite || echo "enable it with: hermes plugins enable selenite"
    echo "Restart the Hermes gateway the supported way to load the hooks."
  fi
fi

if [ "$DRY" = 0 ]; then
  STATE=${SELENITE_STATE:-$HOME/.local/state/selenite}
  mkdir -p "$STATE" && chmod 700 "$STATE"
  if python3 -I "$SKILL/scripts/ledger.py" summary --days 1 >/dev/null; then echo "PASS: ledger works"; else echo "FAIL: ledger"; exit 1; fi
fi
if [ "$FAILED" -gt 0 ]; then
  echo "install finished with $FAILED failure(s) — see the FAIL lines above. Fix or unlock those agent dirs and re-run: install.sh is idempotent." >&2
  exit 1
fi
echo "Try: python3 $SKILL/scripts/cleanse.py   (and: antibeaurocracy audit)"
