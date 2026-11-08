"""Initialize only a pristine database; never upgrade an existing installation."""
import configparser
import importlib.util
import os
from pathlib import Path
import sys

import psycopg2

spec = importlib.util.spec_from_file_location('govopsdev_entrypoint', '/usr/local/bin/govopsdev-entrypoint.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)
config_path = entrypoint.prepare_config(os.environ)
config = configparser.ConfigParser(interpolation=None)
config.read(config_path)
opts = config['options']
modules = Path('/usr/share/doc/govopsdev-erp/erp-modules.txt').read_text().strip()
with psycopg2.connect(host=opts['db_host'], port=opts['db_port'], user=opts['db_user'],
                      password=opts['db_password'], dbname=opts['db_name']) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.ir_module_module')")
        initialized = cursor.fetchone()[0] is not None
        if initialized:
            cursor.execute("SELECT name FROM ir_module_module WHERE state='installed' AND name = ANY(%s)",
                           (modules.split(','),))
            installed = {row[0] for row in cursor.fetchall()}
            if installed != set(modules.split(',')):
                sys.exit('Existing database is incomplete or uses different modules; inspect it before continuing.')
            print('Existing installation found; retaining database and modules.')
            sys.exit(0)
print('Initializing a new database; this can take a few minutes.', flush=True)
sys.argv = ['govopsdev-entrypoint.py', 'odoo', '--init=' + modules, '--without-demo=True',
            '--load-language=th_TH', '--stop-after-init']
entrypoint.main()
