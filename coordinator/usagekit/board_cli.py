"""CLI entry points for the local continuity dashboard."""
import argparse
import json

from . import config, continuity, handoff


def command(args):
    paths = config.get_paths()
    if args.verb == 'startup':
        from . import startup
        if args.mode == 'enable':
            result = startup.enable(paths, handoff.require_root(), args.port, args.codex_account, args.experimental_claude_account)
        elif args.mode == 'disable':
            result = startup.disable(paths)
        else:
            result = startup.startup_status(paths)
        print(json.dumps(result, indent=2))
        return 0
    root = handoff.require_root()
    if args.verb == 'serve':
        from .dashboard import serve
        serve(paths, root, args.port, args.codex_account, args.experimental_claude_account)
        return 0
    if args.verb == 'status':
        result = continuity.snapshot(paths, root, args.type, args.scope, args.risk)
    elif args.verb == 'release':
        result = continuity.release(paths, root, args.workstream, args.owner, args.source_stopped)
    elif args.verb == 'claim':
        result = continuity.claim(paths, root, args.workstream, args.to, args.ticket)
    else:
        result = continuity.run_check(paths, root, args.workstream, args.command, args.timeout)
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.verb == 'status':
        print('Agent Relay | %s | %s' % (root, result['branch']))
        for item in result['workstreams']:
            print('%s | %s | %s | checks: %s | next: %s' %
                  (item['slug'], item['owner'], item['status'], item['verification']['status'], item['next_action']))
        for error in result['errors']:
            print('Warning: ' + error)
        if not result['workstreams']:
            print('No checkpoints yet. Use usagectl handoff prepare, then refresh.')
    else:
        print(json.dumps(result, indent=2))
    return 1 if args.verb == 'check' and result['status'] != 'passed' else 0


def add_parser(top, leaf):
    verbs = top.add_parser('board', help='local continuity dashboard and verified transfers').add_subparsers(dest='verb')
    verbs.required = True
    status = leaf(verbs, 'status', command)
    status.add_argument('--type', default='feature')
    status.add_argument('--scope', choices=('small', 'medium', 'large'), default='small')
    status.add_argument('--risk', choices=('low', 'medium', 'high'), default='medium')
    server = leaf(verbs, 'serve', command)
    server.add_argument('--port', type=int, default=8765)
    server.add_argument('--codex-account', help='poll current Codex CLI login every 60 seconds into this matching alias')
    server.add_argument('--experimental-claude-account', help='opt in to undocumented Claude account quota reads every 180 seconds using local CLI credentials')
    startup = leaf(verbs, 'startup', command)
    startup.add_argument('mode', choices=('enable', 'disable', 'status'))
    startup.add_argument('--port', type=int, default=8766)
    startup.add_argument('--codex-account')
    startup.add_argument('--experimental-claude-account')
    release = leaf(verbs, 'release', command)
    release.add_argument('--workstream', required=True)
    release.add_argument('--owner', required=True)
    release.add_argument('--source-stopped', action='store_true')
    claim = leaf(verbs, 'claim', command)
    claim.add_argument('--workstream', required=True)
    claim.add_argument('--to', required=True)
    claim.add_argument('--ticket', required=True)
    check = leaf(verbs, 'check', command)
    check.add_argument('--workstream', required=True)
    check.add_argument('--timeout', type=int, default=60)
    check.add_argument('command', nargs=argparse.REMAINDER)
