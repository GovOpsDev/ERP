#!/usr/bin/env python3
"""OPERATIONS FIX: quiesced DB/filestore backups and non-destructive fresh restores.

Run only against the named isolated test stacks. Credentials stay in containers.
Every archive must have a manifest and verified checksums before restore.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

IMAGE = 'odoo@sha256:dc76c42d292af9c513de826620e5a5dbe8152383ce8767eb6ed1390a806eb32f'
parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['backup', 'restore'])
parser.add_argument('--db-container', default='erp-readiness20-db-1')
parser.add_argument('--filestore-volume', default='erp-readiness20_filestore')
parser.add_argument('--database', required=True)
parser.add_argument('--archive', type=Path, required=True)
args = parser.parse_args()
if args.db_container not in ['erp-readiness20-db-1', 'erp-finance-test20-db-1']:
    parser.error('Only the designated isolated test DB containers are allowed')
if args.filestore_volume not in ['erp-readiness20_filestore', 'erp-finance-test20_finance_test_odoo']:
    parser.error('Only the designated isolated test filestore volumes are allowed')
if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', args.database):
    parser.error('Unsafe database name')
if args.action == 'restore' and args.db_container != 'erp-readiness20-db-1':
    parser.error('Restores must use the dedicated readiness target')
def assert_quiesced():
    running = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).splitlines()
    if any(n.startswith(('erp-readiness20-app-', 'erp-closure20-odoo-')) or (args.db_container == 'erp-finance-test20-db-1' and n.startswith('erp-finance-test20-') and n != args.db_container) for n in running):
        parser.error('Stop all test Odoo writers before backup')

def db_identity():
    return subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}} {{.State.Running}}',args.db_container],text=True).strip()

if args.action == 'backup':
    assert_quiesced()
    identity_before = db_identity()
    assert identity_before.endswith(' true'), 'Database container is not running'

def run(args_, **kwargs):
    return subprocess.run(args_, check=True, **kwargs)

def pg(*command, **kwargs):
    return run(['docker', 'exec', '-i', args.db_container, *command], **kwargs)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

archive = args.archive.resolve()
if args.action == 'backup':
    archive.mkdir(mode=0o700, parents=True, exist_ok=False)
    db_part = archive/'database.dump.partial'
    with db_part.open('wb') as output:
        pg('sh', '-c', 'exec pg_dump -U "$POSTGRES_USER" -Fc "$1"', 'backup', args.database, stdout=output)
    fs_part = archive/'filestore.tar.gz.partial'
    with fs_part.open('wb') as output:
        run(['docker', 'run', '--rm', '--network', 'none', '--user', '0', '-v', args.filestore_volume+':/source:ro', '--entrypoint', 'tar', IMAGE, '-C', '/source/filestore/'+args.database, '-czf', '-', '.'], stdout=output)
    with db_part.open('rb') as source:
        pg('pg_restore', '--list', stdin=source, stdout=subprocess.DEVNULL)
    with fs_part.open('rb') as source:
        run(['tar', '-tzf', '-'], stdin=source, stdout=subprocess.DEVNULL)
    assert_quiesced()
    assert db_identity() == identity_before, 'Database lifecycle changed during backup; retain partial files'
    db_part.rename(archive/'database.dump')
    fs_part.rename(archive/'filestore.tar.gz')
    manifest={'database':args.database, 'db_container':args.db_container, 'filestore_volume':args.filestore_volume, 'quiesced':True,'db_container_identity':identity_before,
              'files':{n:{'sha256':digest(archive/n), 'bytes':(archive/n).stat().st_size} for n in ['database.dump','filestore.tar.gz']}}
    (archive/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'backup':'verified archive created','database':args.database,'files':manifest['files']},indent=2))
else:
    manifest=json.loads((archive/'manifest.json').read_text())
    for name in ['database.dump','filestore.tar.gz']:
        assert digest(archive/name)==manifest['files'][name]['sha256'], 'Backup checksum mismatch: '+name
    # createdb refuses to overwrite an existing database; never drop a preserved DB.
    pg('sh','-c','exec createdb -U "$POSTGRES_USER" "$1"','restore',args.database)
    with (archive/'database.dump').open('rb') as source:
        pg('sh','-c','exec pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d "$1"','restore',args.database,stdin=source)
    destination='/target/filestore/'+args.database
    run(['docker','run','--rm','--network','none','--user','0','-v',args.filestore_volume+':/target','--entrypoint','mkdir',IMAGE,'-p',destination])
    # A volume first created by a restore helper has root-owned top directories.
    # Odoo needs these writable for sessions and new per-database filestores.
    run(['docker','run','--rm','--network','none','--user','0','-v',args.filestore_volume+':/target','--entrypoint','chown',IMAGE,'odoo:odoo','/target','/target/filestore'])
    with (archive/'filestore.tar.gz').open('rb') as source:
        run(['docker','run','--rm','-i','--network','none','--user','0','-v',args.filestore_volume+':/target','--entrypoint','tar',IMAGE,'-C',destination,'-xzf','-'],stdin=source)
    run(['docker','run','--rm','--network','none','--user','0','-v',args.filestore_volume+':/target','--entrypoint','chown',IMAGE,'-R','odoo:odoo',destination])
    print(json.dumps({'restore':'database and matching filestore restored','source_database':manifest['database'],'target_database':args.database}))
