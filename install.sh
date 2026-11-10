#!/usr/bin/env bash
# Selenite installer: links the frictionless skill into each agent that is
# present, and the plugin into Hermes. Idempotent; links, never copies.
#   ./install.sh            install everywhere detected
#   ./install.sh --dry-run  show what would be linked
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$ROOT/skills/frictionless"
DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1

link() { # src dst
  local src="$1" dst="$2"
  [[ -d "$(dirname "$dst")" ]] || return 0
  if [[ -L "$dst" && "$(readlink -f "$dst")" == "$(readlink -f "$src")" ]]; then echo "ok    $dst"; return; fi
  if [[ -e "$dst" ]]; then echo "skip  $dst (exists; not a Selenite link)"; return; fi
  if (( DRY )); then echo "would $dst -> $src"; else ln -s "$src" "$dst" && echo "link  $dst"; fi
}

# Agent Skills-format skill directories (the open SKILL.md standard).
for d in "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.codex/skills" \
         "$HOME/.config/opencode/skills" "$HOME/.hermes/skills"; do
  link "$SKILL" "$d/frictionless"
done
# Hermes plugin (the repo root is the plugin).
link "$ROOT" "$HOME/.hermes/plugins/selenite"

mkdir -p "${SELENITE_STATE:-$HOME/.local/state/selenite}"
chmod 700 "${SELENITE_STATE:-$HOME/.local/state/selenite}"
python3 -I "$SKILL/scripts/ledger.py" summary --days 1 >/dev/null && echo "PASS: ledger works" || echo "FAIL: ledger"
echo "Hermes: restart the gateway the supported way to load the plugin."
