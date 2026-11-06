# Personal Relay access

Each person runs their own Relay instance on the computer holding their repositories
and provider CLI logins. Paired devices can view its workspace, refresh usage and
release/claim ownership. This version has one owner, not multiple users or roles.
Provider credentials stay on that computer. It must be awake and reachable.

Choose a profile; switching modes does not require changing application code:

| Mode | Where it works | HTTPS certificate | Network setup |
|---|---|---|---|
| `lan` | Same Wi-Fi/LAN | Caddy local CA, trusted on each device | Bind a specific LAN IP; permit only intended LAN clients |
| `private` | Your VPN/private network | Caddy local CA, trusted on each device | Bind the VPN interface IP; VPN routes/ACLs must allow it |
| `public` | Internet | Caddy automatic public certificate | Domain DNS and inbound HTTPS reachability |

All modes use the same device authentication, HTTPS requirement and ownership
safeguards. A VPN does not bypass authentication. A public URL is not anonymous.
Local-only `board serve` remains the default and requires no extra dependency.

## Architecture

```text
Phone HTTPS -> Caddy on selected interface -> Waitress on 127.0.0.1
             -> authenticated, fixed-route gateway -> private loopback dashboard
```

The gateway checks exact Host/Origin, HTTPS proxy context, session and mutation
CSRF token. It ignores forwarded identity headers. It never binds to a LAN/public
interface; Caddy runs on the same computer and terminates TLS. Do not replace this
with a tunnel pointing directly at the ordinary local dashboard. TLS trust is a
deployment requirement, including on Wi-Fi. Do not bypass certificate warnings.

The legacy dashboard server is only an internal backend. Waitress bounds remote
connections/headers/bodies, and Caddy handles TLS. Proxy and backend are on the same
trusted computer: untrusted local OS users are outside this personal-instance model.
Profiles bind to a specific repository. Moving to another repository requires a
new/reconfigured profile and fresh device pairing.

## Install optional components

From this checkout, in the Python environment you use to run Relay:

```powershell
python -m pip install -r coordinator/requirements-remote.txt
```

Install Caddy from its [official distribution](https://caddyserver.com/docs/install).
The kit does not silently install or start Caddy, change firewall rules, create DNS
records, trust certificates, or join a VPN. Configuration commands below only write
local profile data. They do not expose a port.

## Configure a mode

Run from the project repository to expose. Replace example names/IPs with addresses
that actually belong to your computer. For LAN/private mode, arrange for the chosen
hostname to resolve to that interface, or use its IP in the HTTPS origin instead.
The HTTPS port and loopback gateway port must differ.

```powershell
# Same Wi-Fi; use your actual LAN address.
python coordinator/usagectl.py board access configure --profile home --mode lan --origin https://192.168.1.20:8443 --bind-address 192.168.1.20 --port 8770

# Private network; use your actual VPN-assigned address.
python coordinator/usagectl.py board access configure --profile vpn --mode private --origin https://100.80.1.2:8443 --bind-address 100.80.1.2 --port 8770

# Public HTTPS; use a domain you control. This explicitly permits a wildcard TLS listener.
python coordinator/usagectl.py board access configure --profile web --mode public --origin https://relay.your-domain.com --bind-address 0.0.0.0 --port 8770

python coordinator/usagectl.py board access status
```

These examples are alternatives using the same gateway port. Run one at a time.
LAN accepts RFC1918 IPv4/ULA IPv6 interfaces; private mode also accepts CGNAT
addresses used by many VPNs. Neither accepts wildcard or link-local addresses.
Scoped IPv6 addresses and noncanonical origins are rejected. Public mode requires
a DNS domain. It does not supply a domain, hosting, NAT traversal or firewall rules.
IPv4 public wildcard binding does not automatically configure IPv6 routing.

Reconfiguring a profile revokes its sessions and pending code. Restart its gateway
and Caddy afterward; a running gateway rejects a changed profile rather than silently
using new network/repository settings. Names separate profiles, not provider logins.

## Review and activate

For the chosen profile, generate a Caddyfile outside Git (example: `home`):

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\AgentRelay" | Out-Null
python coordinator/usagectl.py board access caddyfile --profile home | Set-Content -Encoding ascii "$env:LOCALAPPDATA\AgentRelay\Caddyfile"
caddy adapt --config "$env:LOCALAPPDATA\AgentRelay\Caddyfile" --adapter caddyfile --pretty
```

Review the origin, bind address and loopback target. The generated file disables
Caddy's admin API and automatic HTTP redirects. No access logging is configured.
For public ACME issuance, Caddy may still use challenge listeners; arrange domain
validation and intended firewall exposure according to Caddy's documentation.

When ready to activate, run these in separate terminals:

```powershell
python coordinator/usagectl.py board serve --access-profile home
caddy run --config "$env:LOCALAPPDATA\AgentRelay\Caddyfile" --adapter caddyfile
```

`--access-profile` takes its port from the profile; the ordinary `--port` argument
does not override it. Optionally add `--codex-account YOUR_ALIAS` and
`--experimental-claude-account YOUR_ALIAS` to preserve your chosen polling behavior.
Aliases must match local provider CLI logins; they do not select credentials.
When replacing an existing polling instance, stop that instance first. Avoid running
duplicate provider pollers for the same account in separate local/remote servers.

For LAN/private profiles, securely install Caddy's public root CA certificate as a
trusted certificate on each device. Follow Caddy and your device's certificate-trust
instructions; never copy the CA private key. Headscale/private-network usage does not
assume Tailscale's hosted certificate service. Public mode uses a real DNS name and
publicly trusted certificates instead. Caddy must obtain a certificate successfully
before the phone can pair. Certificate trust and real network connectivity need a
deployment check on your devices.

## Pair, sign out and revoke

On the computer:

```powershell
python coordinator/usagectl.py board access pair --profile home
```

Visit the configured HTTPS URL on the phone, enter a device name and the displayed
code. The code is random, valid for ten minutes, and single-use. Issuing another code
replaces the previous one. Do not put codes in URLs, tickets, chat or shared logs.
The form clears the code after submission. Pairing failures share a 20-attempt/minute
limit per profile, so hostile traffic can temporarily block new pairing.

Sessions last eight hours (absolute expiry), with at most 32 active devices per
profile. Cookies are Secure, HttpOnly and SameSite=Strict. Codes/session credentials
are hashed in local storage. The same profile works across supported device browsers.
Each paired device has full personal-owner access, including quota refresh and
ownership transfers; there is no read-only or shared-team role in this version.

Use **Sign out** on the phone, or revoke from the computer:

```powershell
python coordinator/usagectl.py board access sessions --profile home
python coordinator/usagectl.py board access revoke --profile home --session SESSION_ID
python coordinator/usagectl.py board access revoke --profile home --session all
```

`all` also cancels the pending pairing code. Expired/revoked sessions return to the
pairing page on the next API response. Requests already authenticated may finish;
revocation does not undo an ownership transfer. Stop the source writer before
confirming release, exactly as on the local dashboard. Transfers still validate the
checkpoint/repository and consume one-use release tickets. Mobile cannot start
arbitrary commands or launch model sessions.

## Startup and rollback

Windows startup can launch the gateway for a profile:

```powershell
python coordinator/usagectl.py board startup enable --access-profile home
```

If startup is already installed, disable it first, then enable with the desired
profile and provider options. This manages the gateway only: Caddy has its own
deployment lifecycle. Install the optional Python dependency into the interpreter
used by startup. There is one startup supervisor per Relay state home.

To remove remote reachability, stop Caddy and the gateway (Ctrl+C for foreground
processes; `board startup disable` for the managed gateway), revoke all sessions,
and undo any firewall/DNS/VPN changes you made. Caddy's generated configuration has
its admin API disabled, so use process/service controls rather than `caddy stop`.
Return to ordinary `board serve` for loopback-only access.

## Storage and verification

Profiles, hashed credentials, session metadata and the last 1,000 audit entries live
in `~/.claude-setup/state/relay-access.sqlite3` (or `CLAUDE_SETUP_HOME`). Audit records
contain session ID, action path, time and outcome; no codes, cookies, provider tokens
or request bodies. Outcome 0 marks an accepted request whose completion may be
unknown. Protect the state directory using your OS account permissions and backups.

```powershell
python -m unittest tests.test_access tests.test_remote_dashboard -q
node tests/test_remote_ui.js
node tests/test_dashboard_ui.js
```

For the optional end-to-end loopback TLS smoke test, install remote requirements,
set `RELAY_TEST_CADDY` to an existing Caddy executable, then run
`python -m unittest tests.test_remote_tls -q`. It uses isolated Caddy storage,
disables system trust installation and trusts the temporary CA only in its client.

The Waitress network-path test skips if the optional dependency is missing. Local
tests cover all three profile modes without provider calls. They do not prove actual
Wi-Fi/VPN/public routing, certificate trust, firewall rules, or mobile rendering.

References: [Waitress deployment](https://docs.pylonsproject.org/projects/waitress/en/latest/),
[Caddy HTTPS](https://caddyserver.com/docs/automatic-https),
[Caddy interface binding](https://caddyserver.com/docs/caddyfile/directives/bind),
[OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
