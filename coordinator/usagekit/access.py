"""Personal access profiles, hashed device credentials and bounded local audit."""
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from . import config
from .errors import CtlError

SESSION_SECONDS = 8 * 3600
PAIR_SECONDS = 600
PRIVATE_NETS = tuple(ipaddress.ip_network(value) for value in
                    ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7'))
VPN_NET = ipaddress.ip_network('100.64.0.0/10')


def db_path(paths):
    return str(Path(paths.state) / 'relay-access.sqlite3')


@contextmanager
def database(paths):
    config.ensure_writable(paths)
    Path(paths.state).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path(paths), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        if os.name != 'nt':
            os.chmod(db_path(paths), 0o600)
        db.executescript('''
          CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS codes(profile TEXT PRIMARY KEY, digest TEXT, created REAL, expires REAL);
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, profile TEXT, digest TEXT UNIQUE,
            csrf TEXT, label TEXT, created REAL, expires REAL);
          CREATE TABLE IF NOT EXISTS attempts(profile TEXT PRIMARY KEY, start REAL, failures INTEGER);
          CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL, profile TEXT,
            session_id TEXT, action TEXT, outcome INTEGER);
        ''')
        db.execute('BEGIN IMMEDIATE')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validate_profile(name, mode, origin, bind_address, port):
    if not isinstance(name, str) or not config.SLUG_RE.fullmatch(name):
        raise CtlError('Profile name must be lowercase letters, digits and hyphens (max 64).')
    if mode not in ('lan', 'private', 'public') or isinstance(port, bool) or not 1 <= port <= 65535:
        raise CtlError('Choose lan/private/public and a gateway port from 1 to 65535.')
    try:
        if not isinstance(origin, str) or '%' in origin or any(c.isspace() for c in origin):
            raise ValueError()
        url = urlsplit(origin)
        host = url.hostname or ''
        if (url.scheme != 'https' or url.username is not None or url.password is not None or
                url.path or url.query or url.fragment or not host or url.port == port):
            raise ValueError()
        try:
            host_ip = ipaddress.ip_address(host)
            host_text = '[' + str(host_ip) + ']' if host_ip.version == 6 else str(host_ip)
        except ValueError:
            host_ip = None
            if len(host) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                                          for label in host.split('.')):
                raise ValueError()
            host_text = host
        if mode == 'public' and (host_ip or '.' not in host or host.endswith(('.localhost', '.local', '.home'))):
            raise ValueError()
        canonical = 'https://' + host_text + (':' + str(url.port) if url.port and url.port != 443 else '')
        if origin != canonical or (url.port or 443) == port:
            raise ValueError()
        if not isinstance(bind_address, str) or '%' in bind_address or any(c.isspace() for c in bind_address):
            raise ValueError()
        address = ipaddress.ip_address(bind_address)
        if str(address) != bind_address:
            raise ValueError()
        if address.is_multicast or address.is_loopback or address.is_link_local:
            raise ValueError()
        private = any(address in network for network in PRIVATE_NETS)
        if mode == 'lan' and not private:
            raise ValueError()
        if mode == 'private' and not (private or address in VPN_NET):
            raise ValueError()
    except (ValueError, TypeError):
        raise CtlError('Use a canonical HTTPS origin without a path, and an explicit interface IP. '
                       'LAN/private require private addresses; public requires a DNS domain. '
                       'HTTPS and gateway ports must differ.') from None


def configure(paths, root, name, mode, origin, bind_address, port):
    validate_profile(name, mode, origin, bind_address, port)
    profile = dict(name=name, mode=mode, origin=origin, bind_address=bind_address, port=port,
                   root=str(Path(root).resolve()), revision=secrets.token_hex(16))
    with database(paths) as db:
        db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)', (name, json.dumps(profile)))
        db.execute('DELETE FROM codes WHERE profile=?', (name,))
        db.execute('DELETE FROM sessions WHERE profile=?', (name,))
    return profile


def load_profile(paths, name, root=None):
    with database(paths) as db:
        row = db.execute('SELECT data FROM profiles WHERE name=?', (name,)).fetchone()
    if not row:
        raise CtlError('Unknown access profile. Run board access configure first.')
    profile = json.loads(row['data'])
    validate_profile(**{key: profile[key] for key in ('name', 'mode', 'origin', 'bind_address', 'port')})
    if root is not None and os.path.normcase(str(Path(root).resolve())) != os.path.normcase(profile['root']):
        raise CtlError('Access profile belongs to another repository; configure a separate profile.')
    return profile


def profiles(paths):
    with database(paths) as db:
        return [json.loads(row['data']) for row in db.execute('SELECT data FROM profiles ORDER BY name')]


def pair_code(paths, profile):
    revision = load_profile(paths, profile)['revision']
    code, clock = secrets.token_urlsafe(24), time.time()
    with database(paths) as db:
        if not revision_matches(db, profile, revision):
            raise CtlError('Access profile changed while issuing the code. Retry with its new configuration.')
        db.execute('INSERT OR REPLACE INTO codes VALUES (?,?,?,?)',
                   (profile, digest(code), clock, clock + PAIR_SECONDS))
    return code


def revision_matches(db, profile, expected):
    row = db.execute('SELECT data FROM profiles WHERE name=?', (profile,)).fetchone()
    return bool(row and (expected is None or json.loads(row['data'])['revision'] == expected))


def pair(paths, profile, code, label, expected_revision=None):
    if not isinstance(code, str) or len(code) > 128 or not isinstance(label, str) or not 1 <= len(label.strip()) <= 60:
        return None
    clock = time.time()
    with database(paths) as db:
        if not revision_matches(db, profile, expected_revision):
            return None
        row = db.execute('SELECT * FROM attempts WHERE profile=?', (profile,)).fetchone()
        start, failures = (row['start'], row['failures']) if row else (clock, 0)
        if clock - start >= 60 or clock < start:
            start, failures = clock, 0
        if failures >= 20:
            return None
        row = db.execute('SELECT * FROM codes WHERE profile=?', (profile,)).fetchone()
        if not row or not row['created'] <= clock < row['expires'] or not secrets.compare_digest(row['digest'], digest(code)):
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)', (profile, start, failures + 1))
            return None
        db.execute('DELETE FROM sessions WHERE expires<=?', (clock,))
        if db.execute('SELECT count(*) FROM sessions WHERE profile=?', (profile,)).fetchone()[0] >= 32:
            return None
        token, csrf, sid = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_hex(12)
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?)',
                   (sid, profile, digest(token), csrf, label.strip(), clock, clock + SESSION_SECONDS))
        db.execute('DELETE FROM codes WHERE profile=?', (profile,))
        return dict(id=sid, token=token, csrf=csrf, label=label.strip(), expires=clock + SESSION_SECONDS)


def authenticate(paths, profile, token, expected_revision=None):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return None
    clock = time.time()
    with database(paths) as db:
        if not revision_matches(db, profile, expected_revision):
            return None
        row = db.execute('SELECT id,csrf,label,expires FROM sessions WHERE profile=? AND digest=? '
                         'AND created<=? AND expires>?', (profile, digest(token), clock, clock)).fetchone()
    return dict(row) if row else None


def sessions(paths, profile):
    load_profile(paths, profile)
    with database(paths) as db:
        return [dict(row) for row in db.execute('SELECT id,label,created,expires FROM sessions '
                 'WHERE profile=? AND expires>? ORDER BY created', (profile, time.time()))]


def revoke(paths, profile, session_id):
    load_profile(paths, profile)
    with database(paths) as db:
        if session_id == 'all':
            db.execute('DELETE FROM sessions WHERE profile=?', (profile,))
            db.execute('DELETE FROM codes WHERE profile=?', (profile,))
        else:
            db.execute('DELETE FROM sessions WHERE profile=? AND id=?', (profile, session_id))


def audit(paths, profile, session_id, action, outcome):
    with database(paths) as db:
        db.execute('INSERT INTO audit(at,profile,session_id,action,outcome) VALUES (?,?,?,?,?)',
                   (time.time(), profile, session_id, action, outcome))
        db.execute('DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 1000)')


def caddyfile(profile):
    validate_profile(**{key: profile[key] for key in ('name', 'mode', 'origin', 'bind_address', 'port')})
    tls = '    tls internal\n' if profile['mode'] != 'public' else ''
    return ('{\n    admin off\n    auto_https disable_redirects\n}\n\n' + profile['origin'] + ' {\n' +
            '    bind ' + profile['bind_address'] + '\n' + tls +
            '    request_body {\n        max_size 8KB\n    }\n' +
            '    reverse_proxy 127.0.0.1:' + str(profile['port']) + '\n}\n')
