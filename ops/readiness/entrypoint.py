"""OPERATIONS FIX: explicit, secret-file based, pinned UAT runtime configuration."""
import configparser
import os
from pathlib import Path
import sys

config = configparser.ConfigParser(interpolation=None)
config['options'] = {
    'db_host': 'db', 'db_port': '5432', 'db_user': 'odoo',
    'db_password': Path('/run/secrets/db_password').read_text().strip(),
    'admin_passwd': Path('/run/secrets/admin_password').read_text().strip(),
    'data_dir': '/var/lib/odoo', 'list_db': 'False', 'proxy_mode': 'True',
    'http_interface': '0.0.0.0',
    'workers': os.environ.get('ERP_WORKERS', '2'),
    'max_cron_threads': os.environ.get('ERP_CRON_THREADS', '0'),
    'db_maxconn': '32', 'limit_time_cpu': '120', 'limit_time_real': '180',
    'limit_memory_soft': '805306368', 'limit_memory_hard': '1073741824',
    'addons_path': ','.join(['/mnt/erp/shared/erp_core/addons'] + [
        f'/mnt/erp/projects/{domain}/addons' for domain in
        ['organization', 'budget', 'procurement', 'finance', 'inventory', 'contract', 'asset']]),
}
os.umask(0o077)
with open('/tmp/erp-runtime.conf', 'w') as output:
    config.write(output)
args = sys.argv[1:]
if args and args[0] == 'shell':
    args = ['shell', '-c', '/tmp/erp-runtime.conf', *args[1:]]
else:
    args = ['-c', '/tmp/erp-runtime.conf', *args]
os.execv('/usr/bin/odoo', ['/usr/bin/odoo', *args])
