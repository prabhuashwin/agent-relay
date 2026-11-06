# Mobile dashboard implementation plan

Approved direction: compact account summaries, one details disclosure per account,
and persistent Accounts/Workstreams navigation. Keep warnings visible and preserve
refresh and transfer safeguards. Existing vanilla HTML/CSS/JS remains the stack.

- Add regression coverage for collapsed mobile details, preserved disclosure state,
  quota summaries, and stale/failed readings.
- Render compact quota summaries and group existing controls/history in one native
  details element. Keep detailed desktop view open by default.
- Replace the phone spacing patch with a compact toolbar, readable summaries and
  bottom anchor navigation with safe-area clearance. Preserve desktop styles.
- Use isolated browser fixtures (no provider calls) at 360/390/430px, desktop,
  landscape and enlarged text. Check overflow, disclosure, navigation and warnings.
- Run existing UI suites, inspect screenshots, verify live assets and update handoff.

Completed: regression checks, implementation, browser matrix and read-only review.
Physical Android review remains after reload; no live provider calls made.

Refinement complete: quota rows replace columns, matching timestamps share a label,
different ages remain separate, section status is concise, and bottom navigation
highlights the section in view. Browser fixtures now match the user's 3+1 quota
shape; width/text/error matrix and explicit navigation-highlight checks pass.
