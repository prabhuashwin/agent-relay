# Personal Relay access implementation plan

Approved scope: personal instances supporting LAN, private networks and public
HTTPS, including usage refresh and guarded ownership transfers. No shared users.

Architecture: optional Waitress gateway behind Caddy TLS, bound to loopback.
The existing local dashboard runs as an internal loopback backend. The gateway
authenticates every data/action request and forwards only fixed routes, with its
own session CSRF tokens. It does not trust forwarded identity headers. Local-only
mode remains dependency-free. Profiles and authentication state live outside Git.

Personal-device pairing uses a random one-time code (ten minutes), generated only
by local CLI. Sessions last eight hours and are revocable. Codes/session tokens
are stored hashed; labels and safe action audit metadata are local SQLite data.
All remote profiles require HTTPS. LAN/private profiles require explicit private
interface addresses; public profiles require a DNS domain. Caddy configuration is
generated for user review; no listeners/firewall/VPN/cert trust changes are made.

- [x] Test profile validation, scope binding, pair-code expiry/replay, concurrent
  use, rate limiting, session expiry/revocation and safe audit storage.
- [x] Implement `access.py` (profile/auth state) and `access_cli.py` (configure,
  status, Caddy export, pairing, sessions, revoke). Add remote dependency manifest.
- [x] Test and implement `remote_dashboard.py`: exact origin/Host checks, fixed
  routes, no unauthenticated data, Secure/HttpOnly/SameSite cookies, CSRF, bounded
  bodies, safe errors, persistent logout and forwarding to the local backend.
- [x] Test and implement `--access-profile` for serve/startup, plus device pairing
  UI and logout. Browser never receives provider credentials or backend tokens.
- [x] Run isolated HTTP/auth tests for all modes and refresh/transfer operations;
  test production Waitress locally without provider calls. Run existing dashboard
  and startup regressions, JavaScript checks, then independent read-only review.
- [x] Document exact setup/activation commands, certificate trust, network limits,
  rollback/revocation and personal-instance constraints; update handoff/decisions.

Delivery is implementation plus validated local configuration; activating public
or network access is a separate explicit step after domain/interface selection.
