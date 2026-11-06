"""Local-only administration of personal remote access; never opens a listener."""
import json
from . import access, config, handoff


def command(args):
    paths = config.get_paths()
    if args.operation == 'configure':
        result = access.configure(paths, handoff.require_root(), args.profile, args.mode,
                                  args.origin, args.bind_address, args.port)
    elif args.operation == 'status':
        result = access.profiles(paths)
    elif args.operation == 'caddyfile':
        print(access.caddyfile(access.load_profile(paths, args.profile)), end='')
        return 0
    elif args.operation == 'pair':
        result = {'code': access.pair_code(paths, args.profile), 'expires_in_seconds': access.PAIR_SECONDS,
                  'instruction': 'Enter this single-use code on your device at the configured HTTPS URL.'}
    elif args.operation == 'sessions':
        result = access.sessions(paths, args.profile)
    else:
        access.revoke(paths, args.profile, args.session)
        result = {'revoked': args.session, 'profile': args.profile}
    print(json.dumps(result, indent=2))
    return 0


def add_parser(verbs, leaf):
    operations = verbs.add_parser('access', help='personal remote access profiles and devices').add_subparsers(dest='operation', required=True)
    for operation in ('configure', 'status', 'caddyfile', 'pair', 'sessions', 'revoke'):
        parser = leaf(operations, operation, command)
        if operation != 'status':
            parser.add_argument('--profile', required=True)
        if operation == 'configure':
            parser.add_argument('--mode', choices=('lan', 'private', 'public'), required=True)
            parser.add_argument('--origin', required=True, help='canonical HTTPS URL without path')
            parser.add_argument('--bind-address', required=True, help='Caddy interface IP; never a wildcard in LAN/private mode')
            parser.add_argument('--port', type=int, default=8770, help='loopback gateway port, different from HTTPS port')
        if operation == 'revoke':
            parser.add_argument('--session', required=True, help='session ID, or all (also cancels pending pairing)')
