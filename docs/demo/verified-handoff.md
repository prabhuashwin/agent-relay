# A passing check can become stale

This demo exercises Relay's real CLI against a small, temporary Git repository.
The task and account names are fictional. It does not run Claude or Codex, read
credentials, fetch quota, or measure which tool completes work faster.

You will see:

1. A command executed by Relay produces `passed` evidence.
2. An edit makes that evidence `stale` and the checkpoint no longer matches.
3. Claiming the previously released checkpoint is rejected.
4. A fresh checkpoint and check allow a new release and claim by `demo-codex`.

## Run it on Windows

Requires Git and Python 3.9+ on PATH. Open a **new PowerShell window** in your
Agent Relay checkout (the directory containing `coordinator/usagectl.py`), then
paste the entire block below. No installation or dashboard is needed.

The block restores your directory and Relay state setting when it finishes.
It retains the temporary demo folder so you can inspect its checkpoint. Git user
settings are supplied only for the demo commit; your Git configuration is unchanged.

```powershell
$relay = (Resolve-Path coordinator/usagectl.py).Path
$demoRoot = Join-Path ([IO.Path]::GetTempPath()) ("relay-proof-" + [guid]::NewGuid())
$demoRepo = Join-Path $demoRoot "repo"
$savedRelayHome = $env:CLAUDE_SETUP_HOME
New-Item -ItemType Directory -Path $demoRepo -Force | Out-Null

function Invoke-Relay {
    & python $relay @args
    if ($LASTEXITCODE -ne 0) { throw "Relay command failed: $args" }
}
function Show-Evidence {
    $board = Invoke-Relay board status --json | ConvertFrom-Json
    $item = $board.workstreams | Where-Object slug -eq "demo-task"
    if (-not $item) { throw "Demo workstream missing" }
    Write-Host ("evidence={0}; checkpoint_matches={1}; owner={2}" -f `
        $item.verification.status, $item.checkpoint_matches, $item.owner)
}

Push-Location $demoRepo
try {
    $env:CLAUDE_SETUP_HOME = Join-Path $demoRoot "state"
    git init -q -b main
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    Set-Content value.txt "1" -Encoding ascii
    Set-Content check.py 'from pathlib import Path; assert int(Path("value.txt").read_text()) > 0; print("positive value: OK")' -Encoding ascii
    git add value.txt check.py
    if ($LASTEXITCODE -ne 0) { throw "git add failed" }
    git -c user.name=RelayDemo -c user.email=demo@example.invalid -c commit.gpgsign=false -c core.hooksPath=NUL commit -qm "Demo baseline"
    if ($LASTEXITCODE -ne 0) { throw "git commit failed" }
    Invoke-Relay init
    Invoke-Relay account add --account demo-claude --provider claude --plan demo --capability edit
    Invoke-Relay account add --account demo-codex --provider codex --plan demo --capability edit

    # 1. Record a checkpoint and execute a real check.
    Invoke-Relay handoff prepare --workstream demo-task --owner demo-claude --goal "Keep the value positive" --next "Review the value change" --accept "The positive-value check passes"
    Invoke-Relay board check --workstream demo-task --timeout 30 -- python check.py
    Show-Evidence

    # Only this demo terminal writes here; there is no running source agent.
    $released = Invoke-Relay board release --workstream demo-task --owner demo-claude --source-stopped --json | ConvertFrom-Json

    # 2. Simulate an unexpected edit after release. The old pass is now stale.
    Set-Content value.txt "2" -Encoding ascii
    Show-Evidence
    & python $relay board claim --workstream demo-task --to demo-codex --ticket $released.ticket --json
    if ($LASTEXITCODE -eq 0) { throw "Expected the changed-tree claim to be rejected" }
    Write-Host "Expected rejection: the released checkpoint no longer matches."

    # 3. Reconcile as the original owner, record current state, and rerun.
    Invoke-Relay handoff prepare --workstream demo-task --owner demo-claude --goal "Keep the value positive" --next "Review the value change" --accept "The positive-value check passes" --done "Changed value from 1 to 2; review remains"
    Invoke-Relay board check --workstream demo-task --timeout 30 -- python check.py
    $released = Invoke-Relay board release --workstream demo-task --owner demo-claude --source-stopped --json | ConvertFrom-Json
    $claimed = Invoke-Relay board claim --workstream demo-task --to demo-codex --ticket $released.ticket --json | ConvertFrom-Json
    Show-Evidence
    Write-Host $claimed.prompt
    Write-Host "Inspect the demo at: $demoRoot"
} finally {
    Pop-Location
    $env:CLAUDE_SETUP_HOME = $savedRelayHome
}
```

## What the observations mean

These are expected observations, not a transcript of a live Claude-to-Codex task:

| Point | Evidence | Checkpoint matches | Owner |
|---|---|---|---|
| After the first check | `passed` | `True` | `demo-claude` |
| After the edit | `stale` | `False` | `demo-claude` |
| After refresh, check and claim | `passed` | `True` | `demo-codex` |

The intentional rejected claim prints an error; that is the expected safeguard.
The successful claim prints a resume prompt. It does not launch an agent.
No usage readings were recorded, so unavailable quota or refresh advice is expected.

Changing `1` to `2` still satisfies the check. **Stale means the old evidence no
longer applies to the current repository, not that the code necessarily fails.**
Preparing a new checkpoint alone does not rerun tests; `board check` does that.
A passing check is evidence for that command, not acceptance of the whole task.

## Use it with real work

Write the handoff note with decisions, failed attempts and next actions. Prepare
the checkpoint and run your actual test command through `usagectl board check`.
Stop the source writer before releasing, claim with the configured destination
account, then paste the returned prompt into that agent in the same worktree.
Do not reuse these fictional aliases for real quota tracking.

The fingerprint excludes checkpoint files and ignored files. It cannot detect
changes to external dependencies, environment variables or external services.
Ownership is cooperative: `--source-stopped` is your attestation, not process
detection or an editor lock. These checks complement a handoff note and a terminal
manager; this demo does not establish superiority over Herdr or a plain note.

See [verification and ownership details](../continuity-dashboard.md#verification),
the [full Claude-to-Codex example](../setup-and-reference.md#example-continue-a-claude-task-in-codex),
or return to the [README](../../README.md).
