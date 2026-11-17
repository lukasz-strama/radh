"""Jawny punkt wejścia internal v2; transport v1 pozostaje osobnym poleceniem."""
import argparse
import os
import signal
import sys
from uuid import uuid4

from .internal_http import InternalClient, load_token
from .multi_session import MultiSessionTransport


def main() -> int:
    parser = argparse.ArgumentParser(description='Wielosesyjny proces DH internal v2 (#68).')
    parser.add_argument('--role', choices=('alice', 'bob', 'mallory'), required=True)
    parser.add_argument('--url', default=os.getenv('RADH_COORDINATOR_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--allow-diagnostics', action='store_true')
    args = parser.parse_args()
    try:
        if any(name in os.environ for name in ('RADH_NODE_TEST_SECRET', 'RADH_MALLORY_TEST_X', 'RADH_MALLORY_TEST_Y')):
            raise ValueError()
        path = os.environ.get(f'RADH_{args.role.upper()}_TOKEN_FILE', '')
        token = load_token(args.role, path)
        client = InternalClient(args.url, args.role, token, uuid4().hex)
        transport = MultiSessionTransport(client, max_agents=int(os.getenv('MAX_NODE_AGENTS', '128')),
                                          allow_diagnostics=args.allow_diagnostics)
    except (ValueError, OSError):
        print('Invalid node configuration', file=sys.stderr)
        return 1
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: transport.stop.set())
    try:
        transport.run()
    except Exception:
        print('Node stopped after internal error', file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if transport.failed:
        print('Node stopped; check role credentials and coordinator availability', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
