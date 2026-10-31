#!/usr/bin/env python3
"""OPERATIONS FIX: reproducible local Compose launcher; no secrets in Git/output."""
import argparse
import os
from pathlib import Path
import secrets
import re
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--secrets-dir', required=True, type=Path)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
secret_dir = args.secrets_dir.resolve()
if secret_dir == root or root in secret_dir.parents:
    parser.error('Secrets must be outside the source repositories')
secret_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
secret_names = ['db_password', 'admin_password', 'uat_password']
if any(not (secret_dir / name).exists() for name in secret_names):
    existing = subprocess.run(['docker', 'volume', 'inspect', 'erp-readiness20_db'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if existing.returncode == 0:
        parser.error('Existing DB volume requires its original external secret files; refusing to replace credentials')
for name in secret_names:
    path = secret_dir / name
    if not path.exists():
        # Compose file secrets must be readable by the container's odoo UID.
        # Host directory remains 0700; individual mounts are read-only.
        with path.open('x') as output:
            output.write(secrets.token_urlsafe(48) + '\n')
        path.chmod(0o444)
if not re.fullmatch(r'erp_[a-z0-9_]+', os.environ.get('ERP_DATABASE', 'erp_readiness')):
    parser.error('Only isolated ERP database identifiers are allowed')
env = dict(os.environ, ERP_ROOT=str(root), ERP_SECRETS_DIR=str(secret_dir))
command = args.command
if command[:1] == ['--']:
    command = command[1:]
if not command:
    parser.error('Supply a docker compose command after --')
if command[0] == 'down' and any(x in command for x in ['-v', '--volumes']):
    parser.error('Deleting preserved volumes is prohibited')
if command[0] in ('up', 'run'):
    volume = 'erp-readiness20_filestore'
    exists = subprocess.run(['docker', 'volume', 'inspect', volume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if exists.returncode:
        subprocess.run(['docker', 'volume', 'create', volume], check=True, stdout=subprocess.DEVNULL)
if command[0] == 'run':
    # A one-shot test/shell process is not an HTTP service. Health polling can
    # load a second registry during test teardown and obscure real test results.
    env['ERP_HEALTHCHECK_DISABLED'] = 'true'
raise SystemExit(subprocess.call(['docker', 'compose', '-f', str(root/'ops/readiness/compose.yaml'), *command], env=env))
