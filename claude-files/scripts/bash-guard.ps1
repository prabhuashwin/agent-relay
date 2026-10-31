# PreToolUse hook (matcher: Bash): blocks commands the user must run themselves.
# Exit 2 = block; stderr is shown to Claude.
$ErrorActionPreference = 'SilentlyContinue'
$data = (New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)).ReadToEnd() | ConvertFrom-Json   # stdin is UTF-8
$cmd = [string]$data.tool_input.command
if (-not $cmd) { exit 0 }
$reason = ''
if ($cmd -imatch '\bgit(\s+-{1,2}[A-Za-z0-9_-]+(=\S+|\s+("[^"]*"|''[^'']*''|[^\s-]\S*))?)*\s+push\b') {
  $reason = 'git push'
} elseif ($cmd -imatch '(^|[\s;&|(])aws(\s|$)') {
  $reason = 'aws cli'
} elseif ($cmd -imatch '\bgh\s+(pr\s+merge|repo\s+delete|release\s+(create|delete)|api(\s+.*(-X|--method)[=\s]*(POST|PUT|PATCH|DELETE)\b|(\s.*)?\s(-f|-F|--field|--raw-field)\s))') {
  $reason = 'gh write command'
}
if ($reason) {
  [Console]::Error.WriteLine("[Guard] Blocked ($reason): run it yourself in a terminal. Command: $cmd")
  exit 2
}
exit 0
