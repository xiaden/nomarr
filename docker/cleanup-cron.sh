#!/bin/sh
# Nightly entity cleanup - remove orphaned entities with no songs
cd /app
python3 -m nomarr.interfaces.cli.cli_main cleanup

