#!/bin/sh
# Wrapper script for Nomarr CLI
cd /app
exec python3 -m nomarr.interfaces.cli.main "$@"
