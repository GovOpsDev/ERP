ARG ODOO_BASE=odoo:20.0@sha256:a97a7665e2b9fd890e12785491a2c91d779f800bcbc30873dada1c8748b28f1c
FROM ${ODOO_BASE}

ARG ODOO_BASE
ARG ERP_VERSION=20.0-20261108-hardened1
LABEL org.opencontainers.image.title="GovOpsDev ERP" \
      org.opencontainers.image.description="Thai government ERP baseline for Odoo 20 Community, including Thai Buddhist dates" \
      org.opencontainers.image.version="${ERP_VERSION}" \
      org.opencontainers.image.source="https://github.com/GovOpsDev/ERP" \
      org.opencontainers.image.url="https://github.com/GovOpsDev/ERP" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.vendor="GovOpsDev" \
      org.opencontainers.image.base.name="${ODOO_BASE}"

USER root
ENV PYTHONDONTWRITEBYTECODE=1
# Fix packages identified in the 2026-11-08 base-image vulnerability scan.
# Odoo itself remains the version supplied by the pinned 20.0 image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
       apt libapt-pkg6.0t64 libpcre2-8-0 python3-pil \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && find /usr -xdev -type f -perm /6000 -exec chmod a-s {} +
COPY LICENSE NOTICE.md /usr/share/doc/govopsdev-erp/
COPY <<'GOVOPSDEV_INVENTORY' /usr/local/lib/govopsdev/build_inventory.py
"""Check bundled addon dependencies and fingerprint the actual image sources."""
import argparse
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path


def build_inventory(root):
    native = Path('/usr/lib/python3/dist-packages/odoo/addons')
    manifests = sorted(root.glob('shared/*/addons/*/__manifest__.py'))
    manifests += sorted(root.glob('projects/*/addons/*/__manifest__.py'))
    modules = {}
    for path in manifests:
        name = path.parent.name
        if name in modules:
            raise ValueError(f'Duplicate addon: {name}')
        manifest = ast.literal_eval(path.read_text())
        if not manifest.get('installable', True):
            raise ValueError(f'Addon is not installable: {name}')
        if manifest.get('license') != 'AGPL-3':
            raise ValueError(f'Review the license for {name} before distribution')
        files = {}
        for file in sorted(path.parent.rglob('*')):
            if file.is_symlink():
                raise ValueError(f'Symlinks must be reviewed before inclusion: {file}')
            if file.is_file():
                files[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
        modules[name] = {
            'version': manifest['version'], 'license': manifest['license'],
            'depends': manifest.get('depends', []), 'files': files,
            'external_dependencies': manifest.get('external_dependencies', {}),
        }
    expected = set(Path('/usr/share/doc/govopsdev-erp/erp-modules.txt').read_text().strip().split(','))
    if set(modules) != expected:
        raise ValueError(f'Install list differs from bundled addons: {set(modules) ^ expected}')
    for name, module in modules.items():
        for dependency in module['depends']:
            if dependency not in modules and not (native / dependency / '__manifest__.py').is_file():
                raise ValueError(f'Missing addon dependency: {name} -> {dependency}')
        for dependency in module['external_dependencies'].get('python', []):
            metadata.version(dependency)
    source_hash = hashlib.sha256(json.dumps(modules, sort_keys=True).encode()).hexdigest()
    return {'schema': 1, 'source_sha256': source_hash, 'module_count': len(modules), 'modules': modules}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inventory = build_inventory(args.root)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    print(f"Verified {inventory['module_count']} addons; source SHA-256: {inventory['source_sha256']}")
GOVOPSDEV_INVENTORY
COPY <<'GOVOPSDEV_ENTRYPOINT' /usr/local/bin/govopsdev-entrypoint.py
"""Prepare private runtime configuration and retain the official Odoo entrypoint."""
import configparser
import os
from pathlib import Path
import re
import sys
import tempfile


def validate_secret(value):
    value = value.strip()
    if len(value) < 16 or value.lower() in {'admin', 'odoo', 'password', 'postgres'}:
        raise ValueError('Database and master secrets must contain at least 16 characters and not be a default password')
    return value


def read_secret(filename):
    return validate_secret(Path(filename).read_text())


def prepare_config(environ, *, directory='/tmp'):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(environ.get('ODOO_RC', '/etc/odoo/odoo.conf')):
        raise ValueError('ODOO_RC configuration was not found')
    options = config['options']
    for variable, setting in [('ODOO_ADMIN_PASSWORD_FILE', 'admin_passwd'), ('PASSWORD_FILE', 'db_password')]:
        if environ.get(variable):
            options[setting] = read_secret(environ[variable])
        elif not options.get(setting):
            raise ValueError(f'Set {variable} or supply {setting} in a private mounted ODOO_RC config')
        else:
            options[setting] = validate_secret(options[setting])
    database = environ.get('ERP_DATABASE', 'govopsdev_erp')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', database):
        raise ValueError('ERP_DATABASE must use lowercase letters, digits and underscores, starting with a letter')
    options.update({
        'db_host': environ.get('HOST', options.get('db_host', 'db')),
        'db_port': environ.get('PORT', options.get('db_port', '5432')),
        'db_user': environ.get('USER', options.get('db_user', 'odoo')),
        'db_name': database, 'dbfilter': '^' + re.escape(database) + '$',
        'list_db': 'False',
    })
    for variable, setting in [('ERP_WORKERS', 'workers'), ('ERP_CRON_THREADS', 'max_cron_threads')]:
        if variable in environ:
            value = int(environ[variable])
            if value < 0:
                raise ValueError(f'{variable} must not be negative')
            options[setting] = str(value)
    fd, filename = tempfile.mkstemp(prefix='govopsdev-odoo-', suffix='.conf', dir=directory)
    with os.fdopen(fd, 'w') as output:
        config.write(output)
    return filename


def main():
    args = sys.argv[1:] or ['odoo']
    if args[0] in {'odoo', '--'} or args[0].startswith('-'):
        if os.geteuid() == 0:
            sys.exit('Run the ERP service as the image default unprivileged odoo user')
        try:
            os.environ['ODOO_RC'] = prepare_config(os.environ)
        except (OSError, ValueError, configparser.Error) as error:
            sys.exit(f'ERP configuration error: {error}')
        # The native entrypoint and wait-for-psql.py read DB values from ODOO_RC.
        # No credential is appended to argv or inherited as an env value.
        for key in ('PASSWORD', 'PGPASSWORD', 'PASSWORD_FILE', 'ODOO_ADMIN_PASSWORD_FILE'):
            os.environ.pop(key, None)
    os.execv('/entrypoint.sh', ['/entrypoint.sh', *args])


if __name__ == '__main__':
    main()
GOVOPSDEV_ENTRYPOINT
COPY <<'GOVOPSDEV_CONFIG' /etc/odoo/odoo.conf
[options]
addons_path = /opt/govopsdev/shared/erp_core/addons,/opt/govopsdev/projects/organization/addons,/opt/govopsdev/projects/budget/addons,/opt/govopsdev/projects/procurement/addons,/opt/govopsdev/projects/finance/addons,/opt/govopsdev/projects/inventory/addons,/opt/govopsdev/projects/contract/addons,/opt/govopsdev/projects/asset/addons
data_dir = /var/lib/odoo
http_interface = 0.0.0.0
list_db = False
proxy_mode = False
workers = 0
max_cron_threads = 0
db_maxconn = 32
limit_time_cpu = 120
limit_time_real = 180
limit_memory_soft = 805306368
limit_memory_hard = 1073741824
GOVOPSDEV_CONFIG
COPY <<'GOVOPSDEV_MODULES' /usr/share/doc/govopsdev-erp/erp-modules.txt
erp_core,erp_organization,erp_organization_hr,erp_organization_hr_employee,erp_user_role,erp_budget,erp_procurement,erp_finance,erp_inventory,erp_contract,erp_asset,account_asset_management,account_asset_transfer,report_xlsx,report_xlsx_helper,erp_dashboard_th,erp_budget_dashboard,erp_user_manual,erp_web_thai_date,erp_security
GOVOPSDEV_MODULES
COPY shared/erp_core/addons/ /opt/govopsdev/shared/erp_core/addons/
COPY projects/organization/addons/ /opt/govopsdev/projects/organization/addons/
COPY projects/budget/addons/ /opt/govopsdev/projects/budget/addons/
COPY projects/procurement/addons/ /opt/govopsdev/projects/procurement/addons/
COPY projects/finance/addons/ /opt/govopsdev/projects/finance/addons/
COPY projects/inventory/addons/ /opt/govopsdev/projects/inventory/addons/
COPY projects/contract/addons/ /opt/govopsdev/projects/contract/addons/
COPY projects/asset/addons/ /opt/govopsdev/projects/asset/addons/
RUN python3 /usr/local/lib/govopsdev/build_inventory.py \
      --root /opt/govopsdev \
      --output /usr/share/doc/govopsdev-erp/addons-inventory.json \
    && dpkg-query -W > /usr/share/doc/govopsdev-erp/os-packages.txt \
    && chmod -R a+rX /opt/govopsdev /usr/share/doc/govopsdev-erp \
    && chmod 644 /etc/odoo/odoo.conf /usr/local/bin/govopsdev-entrypoint.py
HEALTHCHECK --interval=30s --timeout=6s --start-period=60s --retries=3 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8069/web/health', timeout=5).read()"
USER odoo
ENTRYPOINT ["python3", "/usr/local/bin/govopsdev-entrypoint.py"]
CMD ["odoo"]
