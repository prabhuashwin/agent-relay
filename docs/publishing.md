# Publish the same main branch to both repositories

Maintain one local `main` and publish that exact history to both repositories:

| Remote | Repository | GitHub login |
|---|---|---|
| `origin` | `ashwinp05/claude-setup` | `ashwinp05` |
| `relay` | `prabhuashwin/agent-relay` (private) | `prabhuashwin` |

Both remotes are configured in the maintainer checkout. In a fresh checkout, inspect `git remote -v` and configure these names before using the commands below. Sign into both accounts using `gh auth login` if needed. Git must use GitHub CLI's credential helper (`gh auth setup-git`). Never commit credentials.

From a clean checkout on `main`, run these commands yourself. Stop if any command fails. The repository's agent rules prohibit automated pushes.

```powershell
gh auth switch --user ashwinp05
git fetch origin main
git merge --ff-only origin/main
gh auth switch --user prabhuashwin
git fetch relay main
git merge --ff-only relay/main
git push relay main
gh auth switch --user ashwinp05
git push origin main
```

If either fast-forward merge fails, reconcile and review the divergent history before publishing. Do not force-push. Direct edits on either GitHub repository can cause this; make changes in the shared local checkout instead.

After both pushes succeed, verify that the three commit hashes match:

```powershell
git rev-parse main
git ls-remote origin refs/heads/main
gh auth switch --user prabhuashwin
git ls-remote relay refs/heads/main
gh auth switch --user ashwinp05
```

Publishing is two separate pushes, not an atomic operation. If only one succeeds, fix access or branch protection for the other and retry the normal push. Until both hashes match, the repositories are not synchronized. The inline README animation and its MP4 travel with these commits; no separate media upload is required.
