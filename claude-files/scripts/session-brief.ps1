# SessionStart hook (matchers: startup|resume|clear): prints open workstreams and latest decisions into context.
# Anything printed here is added to Claude's context.
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$data = (New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)).ReadToEnd() | ConvertFrom-Json   # stdin is UTF-8
$cwd = [string]$data.cwd
if (-not $cwd -or -not (Test-Path -LiteralPath $cwd -PathType Container)) { $cwd = '.' }
$idx = Join-Path $cwd 'handoffs/INDEX.md'
if (Test-Path -LiteralPath $idx -PathType Leaf) {
  Write-Output "[Session brief] Open workstreams (handoffs/INDEX.md):"
  Get-Content -LiteralPath $idx -Encoding UTF8 -TotalCount 40
}
$dec = Join-Path $cwd 'DECISIONS.md'
if (Test-Path -LiteralPath $dec -PathType Leaf) {
  Write-Output "[Session brief] Latest decisions (DECISIONS.md, last 10 lines):"
  Get-Content -LiteralPath $dec -Encoding UTF8 -Tail 10
}
exit 0
