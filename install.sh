#!/usr/bin/env sh
# Installs the skill for Claude Code and Codex (any folder that follows the Agent Skills layout works).
set -e
src="$(cd "$(dirname "$0")" && pwd)"
for base in "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  if [ -d "$(dirname "$base")" ]; then
    dest="$base/adhd"
    mkdir -p "$dest"
    cp -R "$src/SKILL.md" "$src/scripts" "$src/references" "$src/examples" "$dest"
    echo "Installed -> $dest"
  fi
done
echo "Done. Try: 'ADHD, clean my Downloads'"
