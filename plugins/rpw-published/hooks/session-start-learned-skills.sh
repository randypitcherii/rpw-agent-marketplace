#!/bin/bash
# session-start-learned-skills.sh — SessionStart: surface the user's learned-skill index (#2067).
#
# rpw-skill-learner regenerates <learned root>/INDEX.md after every run: one line per live
# learned skill, with its trigger. This hook hands that file to the session as context, so
# learned skills get loaded — a skill no session knows about is archived as never-used.
#
# ON by default, and silent unless the index exists. The learned root is
# $RPW_LEARNED_SKILLS_HOME, else ~/.rpw/learned-skills. A public user without the skill
# learner costs one `test -f` below and never starts Python. The plugin ships this code
# only; the index is the user's own data and is never committed here.
#
# The index derives from transcripts, so it is untrusted: learned_skill_index.py caps it,
# strips control/escape/invisible characters and frames it as data, not instructions.
# Always exits 0 and never prints anything but that one JSON context object.

set +e

root="${RPW_LEARNED_SKILLS_HOME:-}"
root="${root#"${root%%[![:space:]]*}"}"
root="${root%"${root##*[![:space:]]}"}"
[ -n "$root" ] || root="$HOME/.rpw/learned-skills"
case "$root" in "~") root="$HOME" ;; "~/"*) root="$HOME/${root#"~/"}" ;; esac

index="$root/INDEX.md"
[ -f "$index" ] && [ -s "$index" ] && [ ! -L "$index" ] || exit 0

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SCRIPT="$PLUGIN_ROOT/hooks/learned_skill_index.py"
[ -f "$SCRIPT" ] || exit 0

for py in python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$py" >/dev/null 2>&1 \
        && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
        "$py" -I "$SCRIPT" </dev/null 2>/dev/null
        exit 0
    fi
done
exit 0
