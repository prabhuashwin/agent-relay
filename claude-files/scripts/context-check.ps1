# UserPromptSubmit hook: tells Claude when the conversation is getting large.
# Anything printed here is added to Claude's context for this turn.
$ErrorActionPreference = 'SilentlyContinue'
$data = (New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)).ReadToEnd() | ConvertFrom-Json   # stdin is UTF-8
$tokens = 0
$path = $data.transcript_path
if ($path -and (Test-Path -LiteralPath $path)) {
  # Fast scan of the last 300 lines first; fall back to the whole file if no usage record there.
  $sets = @(
    { @(Get-Content -LiteralPath $path -Tail 300) },
    { @(Select-String -LiteralPath $path -Pattern '"usage"','"isCompactSummary":true' -SimpleMatch | ForEach-Object { $_.Line }) }
  )
  foreach ($get in $sets) {
    $lines = @(& $get)
    $found = $false
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
      if ($lines[$i] -like '*"isCompactSummary":true*') { $tokens = 0; $found = $true; break }
      $o = $null
      try { $o = $lines[$i] | ConvertFrom-Json } catch { continue }
      if ($o -and -not $o.isSidechain -and $o.message.usage) {
        $u = $o.message.usage
        $tokens = [int]$u.input_tokens + [int]$u.cache_read_input_tokens + [int]$u.cache_creation_input_tokens
        $found = $true
        break
      }
    }
    if ($found) { break }
  }
}
$k = [math]::Round($tokens / 1000)
$slash = ([string]$data.prompt).TrimStart() -like '/*'

# Log every run so you can confirm the check is firing.
$log = Join-Path $PSScriptRoot 'context-check.log'
Add-Content -LiteralPath $log -Value ("{0}  {1}k  {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $k, $data.session_id)
$logLines = @(Get-Content -LiteralPath $log)
if ($logLines.Count -gt 1000) {
  Set-Content -LiteralPath $log -Value ($logLines | Select-Object -Last 500)
}

if ($tokens -ge 150000) {
  if ($slash) { exit 0 }
  [Console]::Error.WriteLine("[Context check] This conversation is at about ${k}k tokens, so this prompt was blocked to save usage. Run /handoff (saves progress to handoffs/), then /clear, and resend your message in the new session. If you must keep going here, run /compact first.")
  exit 2
} elseif ($tokens -ge 100000) {
  Write-Output "[Context check] This conversation is at about ${k}k tokens. At the end of your reply, add one line telling the user this, and that at 150k their prompts will be blocked until they run /handoff then /clear (or /compact). Suggest doing it now if the current task is nearly done."
}
exit 0
