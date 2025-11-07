#!/bin/sh
cd /app
python3 -m nomarr.interfaces.cli.main cleanup --hours $(python3 -c "import yaml; print(yaml.safe_load(open('/app/config/config.yaml')).get('cleanup_age_hours', 168))")
