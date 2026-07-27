<#
.SYNOPSIS
  Post-session code review for SaReGaMaPic. Diffs the current branch against a
  base, picks a reviewer model by diff risk (tiered: Fable 5 -> Opus 5), then
  runs the session-reviewer agent headless to write review comments to the
  session log and bug findings to the vault backlog.

.DESCRIPTION
  Coding happens on the cheap tier (Opus 4.8/4.7 or Sonnet). This runs AFTER,
  on a newer model, scoped to the diff only so the premium model sees few
  tokens. It never edits app code, commits, or pushes unless you pass -Push.

.EXAMPLE
  powershell -File scripts/session-review.ps1
  powershell -File scripts/session-review.ps1 -Push -CreatePr
  powershell -File scripts/session-review.ps1 -Base main -Model claude-opus-5   # force tier
#>
[CmdletBinding()]
param(
  [string]$Base = 'main',
  [string]$Model,                                   # override the tiered pick
  [switch]$Push,                                    # push branch before review
  [switch]$CreatePr,                                # create PR (needs gh) / print compare URL
  [string]$PermissionMode = 'acceptEdits',          # headless claude permission mode
  [switch]$DryRun                                   # decide tier + target, don't call claude
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# --- 0. sanity ---------------------------------------------------------------
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($branch -eq $Base) {
  Write-Warning "You are ON '$Base'. Review compares a feature branch to its base; nothing to review."
  return
}
$ahead = git rev-list --count "$Base..HEAD"
if ([int]$ahead -eq 0) {
  Write-Host "No commits on '$branch' beyond '$Base'. Nothing to review." -ForegroundColor Yellow
  return
}

# --- 1. measure the diff -----------------------------------------------------
$files    = @(git diff --name-only "$Base...HEAD" | Where-Object { $_ })
$stat     = (git diff --shortstat "$Base...HEAD") -join ' '
$numstat  = @(git diff --numstat  "$Base...HEAD")
$changed  = 0
foreach ($line in $numstat) {
  $p = $line -split "`t"
  if ($p.Count -ge 2) { foreach ($n in $p[0..1]) { if ($n -match '^\d+$') { $changed += [int]$n } } }
}

# --- 2. pick the tier --------------------------------------------------------
# Escalate to Opus 5 when the change is large OR touches high-blast-radius code:
# migrations, the API-contract mirror (schemas.py / types.ts), auth, or the DB layer.
$hotPattern = '(migrations/|schemas\.py|api/types\.ts|/auth|auth\.py|\bdb\.py|security)'
$hotHits    = @($files | Where-Object { $_ -match $hotPattern })
$reasons    = @()
if ($changed -gt 400)      { $reasons += "large diff ($changed lines)" }
if ($files.Count -gt 15)   { $reasons += "$($files.Count) files" }
if ($hotHits)              { $reasons += "touches high-risk paths: $($hotHits -join ', ')" }

if ($Model) {
  $picked = $Model; $why = 'forced via -Model'
} elseif ($reasons.Count -gt 0) {
  $picked = 'claude-opus-5'; $why = ($reasons -join '; ')
} else {
  $picked = 'claude-fable-5'; $why = "routine diff ($changed lines, $($files.Count) files)"
}

# --- 3. locate this session's vault log --------------------------------------
$logDir = 'I:\Dropbox\Obsidian\saregamapic\logs'
$log    = Get-ChildItem $logDir -Filter '*.md' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$logPath = if ($log) { $log.FullName } else { '(none found — reviewer should create/derive one)' }

Write-Host "`n=== session-review ===" -ForegroundColor Cyan
Write-Host "branch : $branch  ->  base $Base  ($ahead commit(s))"
Write-Host "diff   : $stat"
Write-Host "tier   : $picked   ($why)"
Write-Host "log    : $logPath`n"

# --- 4. optional push / PR (gated; commit-only-when-asked) -------------------
if ($Push) {
  Write-Host "Pushing '$branch' to origin..." -ForegroundColor Yellow
  git push -u origin $branch
}
if ($CreatePr) {
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    gh pr create --base $Base --head $branch --fill
  } else {
    $slug = (git remote get-url origin) -replace '^git@github.com:', '' -replace '\.git$',''
    Write-Host "gh not installed — open a PR here:" -ForegroundColor Yellow
    Write-Host "  https://github.com/$slug/compare/$Base...$branch?expand=1"
  }
}

if ($DryRun) { Write-Host "[DryRun] stopping before the review call." -ForegroundColor DarkGray; return }

# --- 5. build the reviewer system prompt from the agent file -----------------
$agentFile = Join-Path $repo '.claude\agents\session-reviewer.md'
$agentRaw  = Get-Content $agentFile -Raw
# strip the YAML frontmatter block, keep the instructions
$sysPrompt = [regex]::Replace($agentRaw, '(?s)^---.*?---\s*', '')

$task = @(
  "Run the SaReGaMaPic post-session review now."
  "- Base to diff against: $Base   (use: git diff $Base...HEAD)"
  "- Session log to append your review to: $logPath"
  "- Model tier selected by the engine: $picked  (reason: $why)"
  "- Diff summary: $stat across $($files.Count) file(s)."
  "Follow your output contract exactly: review comments into the session log,"
  "each bug as an F-numbered finding in saregamapic-review-findings.md."
  "Do not edit app code, commit, push, or open PRs."
) -join "`n"

# --- 6. run the reviewer headless on the picked model ------------------------
Write-Host "Launching reviewer on $picked ..." -ForegroundColor Green
claude -p $task --model $picked --append-system-prompt $sysPrompt --permission-mode $PermissionMode
Write-Host "`nReview complete. Check the log and saregamapic-review-findings.md." -ForegroundColor Cyan
