# Claude Code status line (terminal only): model + current context size.
$ErrorActionPreference = 'SilentlyContinue'
$data  = (New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)).ReadToEnd() | ConvertFrom-Json   # stdin is UTF-8
$model = $data.model.display_name
$tokens = 0
$path = $data.transcript_path
$cu = $data.context_window.current_usage
if ($cu) {
  $tokens = [int]$cu.input_tokens + [int]$cu.cache_creation_input_tokens + [int]$cu.cache_read_input_tokens
} elseif ($path -and (Test-Path -LiteralPath $path)) {
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
$e = [char]27
if     ($tokens -ge 150000) { $c = "$e[31m"; $tip = ' - /handoff then /clear' }
elseif ($tokens -ge 100000) { $c = "$e[33m"; $tip = ' - /compact soon' }
else                        { $c = "$e[32m"; $tip = '' }
Write-Output ("{0} | {1}ctx {2}k{3}{4}[0m" -f $model, $c, $k, $tip, $e)
