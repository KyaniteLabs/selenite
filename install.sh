#!/usr/bin/env sh
# Selenite installer. Links the frictionless skill into each agent harness it
# finds, and with --hermes also links and enables the Hermes plugin.
#   ./install.sh             link the skill wherever a harness exists
#   ./install.sh --hermes    also install the Hermes plugin (it registers the skill itself)
#   ./install.sh --dry-run   show what would be linked
# Idempotent. It only creates symlinks and never overwrites a real file or folder.
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

link() {  # link <target> <link-path>
  if [ -L "$2" ] && [ "$(readlink -f "$2")" = "$(readlink -f "$1")" ]; then echo "ok    $2"; return; fi
  if [ -e "$2" ] || [ -L "$2" ]; then echo "skip  $2 (exists, not a Selenite link)"; return; fi
  if [ "$DRY" = 1 ]; then echo "would $2 -> $1"; return; fi
  mkdir -p "$(dirname "$2")"; ln -s "$1" "$2"; echo "link  $2"
}

# Agent Skills-format homes. Hermes is not listed: its plugin registers the skill,
# so linking it into the Hermes skills folder as well would load it twice.
[ -d "$HOME/.claude" ] && link "$SKILL" "$HOME/.claude/skills/frictionless"            # Claude Code
[ -d "$HOME/.agents" ] && link "$SKILL" "$HOME/.agents/skills/frictionless"            # any agentskills reader
[ -d "$HOME/.codex" ] && link "$SKILL" "$HOME/.codex/skills/frictionless"              # Codex
[ -d "$HOME/.config/opencode" ] && link "$SKILL" "$HOME/.config/opencode/skills/frictionless"
true  # a missing harness is not an error
found=0; for d in .claude .agents .codex .config/opencode; do [ -d "$HOME/$d" ] && found=1; done
[ "$found" = 1 ] || [ "$HERMES" = 1 ] || echo "No agent home found (~/.claude, ~/.agents, ~/.codex, ~/.config/opencode), so nothing was linked."

if [ "$HERMES" = 1 ]; then
  HH=${HERMES_HOME:-$HOME/.hermes}
  link "$ROOT" "$HH/plugins/selenite"
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
echo "Try: python3 $SKILL/scripts/cleanse.py"
