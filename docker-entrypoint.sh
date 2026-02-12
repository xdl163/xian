#!/usr/bin/env bash
set -e

if [ -f /app/config.yaml ]; then
  python - <<'PY'
import os
import yaml

config_path = '/app/config.yaml'
with open(config_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}

mapping = {
    'db_host': os.getenv('DB_HOST'),
    'db_port': os.getenv('DB_PORT'),
    'db_user': os.getenv('DB_USER'),
    'db_password': os.getenv('DB_PASSWORD'),
}

changed = False
for k, v in mapping.items():
    if v is not None and v != '':
        if k == 'db_port':
            try:
                v = int(v)
            except Exception:
                pass
        if cfg.get(k) != v:
            cfg[k] = v
            changed = True

if changed:
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    print('[entrypoint] config.yaml database fields updated from env')
PY
fi

exec "$@"
