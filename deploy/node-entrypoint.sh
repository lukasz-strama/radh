#!/bin/sh
set -eu
# Sekrety testowe nie są częścią tego środowiska. Rola i URL są jawną konfiguracją.
case "${RADH_NODE_ROLE:-}" in
    alice|bob|mallory) ;;
    *) echo 'Niepoprawna rola procesu.' >&2; exit 1 ;;
esac
set -- python -m backend.dh_transport --role "$RADH_NODE_ROLE" --url "$RADH_COORDINATOR_URL"
case "${RADH_DIAGNOSTICS:-0}" in
    0) ;;
    1) set -- "$@" --allow-diagnostics ;;
    *) echo 'RADH_DIAGNOSTICS musi wynosić 0 albo 1.' >&2; exit 1 ;;
esac
exec "$@"
