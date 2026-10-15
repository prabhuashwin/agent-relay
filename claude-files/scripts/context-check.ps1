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
    { @(Select-String -LiteralPath $path -Pattern '"usage"' -SimpleMatch | ForEach-Object { $_.Line }) }
  )
  foreach ($get in $sets) {
    $lines = @(& $get)
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
      $o = $null
      try { $o = $lines[$i] | ConvertFrom-Json } catch { continue }
      if ($o -and -not $o.isSidechain -and $o.message.usage) {
        $u = $o.message.usage
        $tokens = [int]$u.input_tokens + [int]$u.cache_read_input_tokens + [int]$u.cache_creation_input_tokens
        break
      }
    }
    if ($tokens) { break }
  }
}
$k = [math]::Round($tokens / 1000)

# Log every run so you can confirm the check is firing.
$log = Join-Path $PSScriptRoot 'context-check.log'
Add-Content -LiteralPath $log -Value ("{0}  {1}k  {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm'), $k, $data.session_id)

if ($tokens -ge 150000) {
  Write-Output "[Context check] This conversation is at about ${k}k tokens, which makes every turn expensive. Start your reply with one line telling the user this, and recommend they run /handoff and then /clear before continuing. Then answer their message normally."
} elseif ($tokens -ge 100000) {
  Write-Output "[Context check] This conversation is at about ${k}k tokens. At the end of your reply, add one line suggesting /compact (with a short focus note) or /handoff if the current task is nearly done."
}
exit 0
