# Installs the skill for Claude Code and Codex (any folder that follows the Agent Skills layout works).
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$targets = @("$HOME\.claude\skills\adhd-or-ocd", "$HOME\.codex\skills\adhd-or-ocd")
foreach ($t in $targets) {
    if (Test-Path (Split-Path $t)) {
        New-Item -ItemType Directory -Force $t | Out-Null
        foreach ($item in "SKILL.md", "scripts", "references", "examples") {
            Copy-Item -Recurse -Force (Join-Path $src $item) $t
        }
        Write-Host "Installed -> $t"
    }
}
Write-Host "Done. Try: 'ADHD or OCD, clean my Downloads'"
