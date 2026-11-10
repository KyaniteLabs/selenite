#!/usr/bin/env sh
# Selenite installer. Links its three skills (frictionless, antibeaurocracy,
# antipedantry) into each agent harness it finds and the `antibeaurocracy` CLI
# into ~/.local/bin; with --hermes it also links and enables the Hermes plugin.
#   ./install.sh             link the skills and CLI wherever a harness exists
#   ./install.sh --hermes    also install the Hermes plugin (it registers all three skills itself)
#   ./install.sh --no-enable link the Hermes plugin, but leave `hermes plugins enable` to you
#   ./install.sh --dry-run   show what would be linked
# Idempotent. It creates symlinks and the state folder, and with --hermes runs
# `hermes plugins enable selenite`. It never overwrites a real file or folder.
#
# A read-only target is normal (an agent seat, a managed Mac, a container): that
# link is skipped, every other target is still attempted, and the last line is
# the count. Only a real failure makes the run exit non-zero.
#
# `hermes plugins enable` is the last step and nothing depends on it: on a
# source checkout Hermes may finish a pending code update and rebuild its
# desktop app first, which takes minutes. --no-enable skips it and prints the
# command, so a caller with its own timeout never loses the install.
set -eu
ROOT=$(cd "$(dirname "$0")" && pwd)
SKILL="$ROOT/skills/frictionless"
DRY=0; HERMES=0; ENABLE=1; CODE=0
LINKED=0; SKIPPED=0; READONLY=0; FAILED=0; FAILED_AT=""; STATE=""

for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --hermes) HERMES=1 ;;
    --no-enable) ENABLE=0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

skip() {  # skip <path> <reason>
  SKIPPED=$((SKIPPED + 1)); echo "skip  $1 ($2)"
}
skip_readonly() { READONLY=$((READONLY + 1)); skip "$1" "read-only"; }
fail() {  # fail <path> <reason>: recorded, reported at the end, never fatal mid-run
  FAILED=$((FAILED + 1)); FAILED_AT="$FAILED_AT
  $1: $2"
  echo "FAIL  $1: $2" >&2
}

writable_parent() {  # 0 when the nearest folder that exists above <path> takes a write
  _x=$1
  while [ ! -e "$_x" ] && [ "$_x" != "/" ] && [ "$_x" != "." ]; do _x=$(dirname "$_x"); done
  [ -w "$_x" ]
}

link() {  # link <target> <link-path>; never fatal, always continues
  _t=$1 _d=$2
  if [ -L "$_d" ] && [ "$(readlink -f "$_d" 2>/dev/null)" = "$(readlink -f "$_t" 2>/dev/null)" ]; then
    echo "ok    $_d"; LINKED=$((LINKED + 1)); return 0
  fi
  if [ -L "$_d" ] && [ -f "$_d/plugin.yaml" ]; then
    # A link to another Selenite checkout. Hermes admits one source per plugin
    # name (two become "Two workspace members are both named 'selenite'"), so
    # the copy this machine already loads wins and the link is repointed at it.
    if [ "$DRY" = 1 ]; then echo "would repoint $_d -> $_t"; return 0; fi
    if _e=$(ln -sfn "$_t" "$_d" 2>&1); then
      echo "point $_d -> $_t"; LINKED=$((LINKED + 1))
    else
      fail "$_d" "$_e"
    fi
    return 0
  fi
  if [ -d "$_d" ] && [ ! -L "$_d" ]; then
    echo "warn  $_d is a real folder, not a link, so that agent loads it instead of Selenite."
    echo "      Move it aside and run install.sh again."
    SKIPPED=$((SKIPPED + 1)); return 0
  fi
  if [ -e "$_d" ] || [ -L "$_d" ]; then skip "$_d" "exists, not a Selenite link"; return 0; fi
  if [ "$DRY" = 1 ]; then echo "would $_d -> $_t"; return 0; fi
  _p=$(dirname "$_d")
  if ! _e=$(mkdir -p "$_p" 2>&1); then
    if writable_parent "$_d"; then fail "$_d" "$_e"; else skip_readonly "$_d"; fi
    return 0
  fi
  if _e=$(ln -s "$_t" "$_d" 2>&1); then
    echo "link  $_d"; LINKED=$((LINKED + 1)); return 0
  fi
  # A read-only filesystem is the product's normal seat, not a defect: say so
  # and keep going. Anything else (a full disk, a permission wall) is a failure.
  if writable_parent "$_d"; then fail "$_d" "$_e"; else skip_readonly "$_d"; fi
}

# Agent Skills-format homes. Hermes is not listed: its plugin registers the skills,
# so linking them into the Hermes skills folder as well would load them twice.
for NAME in frictionless antibeaurocracy antipedantry; do
  for H in .claude .agents .codex .config/opencode; do   # Claude Code, any agentskills reader, Codex, OpenCode
    if [ -d "$HOME/$H" ]; then link "$ROOT/skills/$NAME" "$HOME/$H/skills/$NAME"; fi
  done
done
link "$ROOT/bin/antibeaurocracy" "$HOME/.local/bin/antibeaurocracy"   # the fake-gate CLI, for any shell
true  # a missing harness is not an error
found=0; for d in .claude .agents .codex .config/opencode; do if [ -d "$HOME/$d" ]; then found=1; fi; done
if [ "$found" = 0 ] && [ "$HERMES" = 0 ]; then
  echo "No agent home found (~/.claude, ~/.agents, ~/.codex, ~/.config/opencode), so nothing was linked."
fi

if [ "$HERMES" = 1 ]; then
  HH=${HERMES_HOME:-$HOME/.hermes}

  # The Selenite this machine already loads, if any: reusing it keeps Hermes at
  # one plugin source, which is the only state its admission accepts.
  existing_install() {  # prints the resolved path; returns 1 when there is none
    _me=$(readlink -f "$ROOT")
    for _cand in "$HOME/.local/share/selenite" "$HOME/.hermes/plugins/selenite" "$HH/plugins/selenite" \
                 "$HOME"/.hermes-org/profiles/*/plugins/selenite; do
      if [ -e "$_cand" ] && [ -f "$_cand/plugin.yaml" ]; then
        _got=$(readlink -f "$_cand" 2>/dev/null) || continue
        if [ "$_got" != "$_me" ]; then printf '%s\n' "$_got"; return 0; fi
      fi
    done
    return 1
  }

  TARGET=$ROOT
  if other=$(existing_install); then
    TARGET=$other
    echo "reuse $TARGET"
    echo "      one Selenite per machine: $ROOT and $TARGET are the same plugin, and a second source breaks Hermes admission."
  fi
  link "$TARGET" "$HH/plugins/selenite"

  # Selenite now carries the fake-gate facet. A standalone antibeaurocracy plugin would run the same hooks twice.
  if [ -e "$HH/plugins/antibeaurocracy" ] || [ -L "$HH/plugins/antibeaurocracy" ]; then
    echo "warn  $HH/plugins/antibeaurocracy is still installed; Selenite includes it now."
    echo "      Disable it so its hooks don't run twice: hermes plugins disable antibeaurocracy"
  fi

  if [ "$DRY" = 0 ]; then
    if [ "$ENABLE" = 1 ] && command -v hermes >/dev/null 2>&1; then
      echo "enable: HERMES_HOME=$HH hermes plugins enable selenite"
      echo "        (on a source checkout Hermes may update itself and rebuild its desktop app first, which takes minutes)"
      if HERMES_HOME=$HH hermes plugins enable selenite; then
        echo "Restart the Hermes gateway the supported way to load the hooks."
      else
        echo "warn  the enable step did not finish; nothing else in this install depends on it." >&2
        echo "      Run it when you like: HERMES_HOME=$HH hermes plugins enable selenite" >&2
      fi
    elif [ "$ENABLE" = 0 ]; then
      echo "enable: skipped (--no-enable); run: HERMES_HOME=$HH hermes plugins enable selenite"
    else
      echo "enable: hermes is not on PATH; run: HERMES_HOME=$HH hermes plugins enable selenite"
    fi
  fi
fi

if [ "$DRY" = 0 ]; then
  # One source of truth for where state goes: the same fallback chain cleanse.py
  # uses, printed by the ledger itself.
  if STATE=$(python3 -I "$SKILL/scripts/ledger.py" state-dir 2>/dev/null); then
    echo "state $STATE"
  else
    echo "warn  no writable state folder: Selenite still runs and prints its findings, but keeps no ledger or report." >&2
    echo "      Set SELENITE_STATE to a writable path to keep them." >&2
  fi
  if [ -z "$STATE" ]; then
    echo "SKIP: ledger (no writable state folder)"
  elif python3 -I "$SKILL/scripts/ledger.py" summary --days 1 >/dev/null 2>&1; then
    echo "PASS: ledger works"
  else
    echo "FAIL: ledger"; CODE=1
  fi
  echo "Try: python3 $SKILL/scripts/cleanse.py   (and: antibeaurocracy audit)"
fi

printf 'Selenite install: %s linked, %s skipped (%s read-only), %s failed.\n' \
  "$LINKED" "$SKIPPED" "$READONLY" "$FAILED"
if [ "$FAILED" -gt 0 ]; then
  printf 'Could not link:%s\n' "$FAILED_AT" >&2
  CODE=1
fi
exit "$CODE"
