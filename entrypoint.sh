#!/bin/sh
set -e

flask db upgrade

if [ "$1" = "gunicorn" ]; then
    shift
    exec gunicorn --bind "0.0.0.0:${PORT}" "$@"
fi

exec "$@"
