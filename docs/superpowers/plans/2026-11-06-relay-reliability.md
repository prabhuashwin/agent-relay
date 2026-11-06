# V2 first increment: startup and connection health

User approved continuing with automatic startup and connection health.

- Add Windows current-user Startup shortcut invoking a hidden Python supervisor.
  Keep its config/status outside the repository; store paths and aliases, never tokens.
  Enable/disable/status commands must be reversible. One supervisor per state home.
  Restart unexpected server exits with bounded delays and stop after repeated crashes.
  Disabling startup stops only its owned child; never kill an unrelated listener.
- Add provider last-attempt, failure count, next-retry and safe actionable error categories.
  Preserve last-success timestamps and stale-data rules; manual failures update health too.
- Test failure/recovery, supervisor retry policy, launch arguments, and opt-in boundaries.
  Run existing quota/dashboard regressions. Verify actual startup installation and HTTP health.
- Record limitations: runs after Windows login, requires awake PC, no remote mobile UI;
  Claude endpoint experimental. Browser visual verification remains separate.
