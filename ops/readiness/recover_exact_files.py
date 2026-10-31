#!/usr/bin/env python3
"""DATA MIGRATION FIX: restore only proven identical files from preserved test copies.

Never overwrite existing files or invent metadata. Restricted to the designated
synthetic UAT target and read-only historical test volume.
"""
import argparse,json,subprocess,re
from pathlib import Path
IMAGE='odoo@sha256:dc76c42d292af9c513de826620e5a5dbe8152383ce8767eb6ed1390a806eb32f'
p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--database',default='erp_readiness');args=p.parse_args()
assert re.fullmatch(r'erp_(readiness|restored|rollback)[a-z0-9_]*',args.database)
sql="SELECT json_build_object('id',id,'store_fname',store_fname,'checksum',checksum,'bytes',file_size) FROM ir_attachment WHERE store_fname IS NOT NULL"
raw=subprocess.check_output(['docker','exec','erp-readiness20-db-1','psql','-U','odoo','-d',args.database,'-At','-c',sql],text=True)
rows=[json.loads(line) for line in raw.splitlines()]
script='''import json,hashlib,re,shutil,sys,os,pwd
from pathlib import Path
payload=json.load(sys.stdin);rows=payload['rows'];source=Path('/source/filestore');target=Path('/target/filestore')/payload['database'];result=[]
owner=pwd.getpwnam('odoo')
for row in rows:
 assert re.fullmatch(r'[a-f0-9]{2}/[a-f0-9]{40}',row['store_fname'])
 assert re.fullmatch(r'[a-f0-9]{40}',row['checksum'])
 path=target/row['store_fname']
 if path.exists():continue
 found=None
 for db in source.iterdir():
  candidate=db/row['store_fname']
  if candidate.is_file():
   data=candidate.read_bytes()
   if len(data)==row['bytes'] and hashlib.sha1(data).hexdigest()==row['checksum']:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as destination:destination.write(data)
    os.chown(path,owner.pw_uid,owner.pw_gid)
    os.chown(path.parent,owner.pw_uid,owner.pw_gid)
    found=db.name;break
 result.append({'id':row['id'],'checksum':row['checksum'],'recovered_from':found})
print(json.dumps(result))
'''
result=subprocess.check_output(['docker','run','--rm','-i','--network','none','--user','0','-v','erp-finance-test20_finance_test_odoo:/source:ro','-v','erp-readiness20_filestore:/target','--entrypoint','python3',IMAGE,'-c',script],input=json.dumps({"rows":rows,"database":args.database}),text=True)
items=json.loads(result);args.output.write_text(json.dumps(items,indent=2)+'\n')
print(json.dumps({'missing':len(items),'recovered':sum(bool(r['recovered_from']) for r in items),'unresolved':[r['id'] for r in items if not r['recovered_from']]}))
raise SystemExit(2 if any(not r['recovered_from'] for r in items) else 0)
