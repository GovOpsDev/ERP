#!/usr/bin/env python3
"""OPERATIONS FIX: read-only checks with machine-readable alerts and exit status.

Exit 0 = checks pass; exit 2 = operational attention. No synthetic transactions.
"""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import urllib.request

p=argparse.ArgumentParser()
p.add_argument('--database',default='erp_readiness')
p.add_argument('--url',default='http://127.0.0.1:18069/web/health')
p.add_argument('--backup',type=Path,required=True)
p.add_argument('--max-backup-age-hours',type=float,default=24)
p.add_argument('--min-disk-free-gb',type=float,default=5)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
assert re.fullmatch(r'erp_[a-z0-9_]+',a.database)
checks={}
def check(name,fn):
    try:
        value=fn()
        checks[name]={'status':'PASS' if value else 'FAIL','value':value}
    except Exception as error:
        checks[name]={'status':'FAIL','error':type(error).__name__}
def sql(query):
    return subprocess.check_output(['docker','exec','erp-readiness20-db-1','psql','-U','odoo','-d',a.database,'-At','-c',query],text=True,stderr=subprocess.DEVNULL,timeout=10).strip()
check('http',lambda:urllib.request.urlopen(a.url,timeout=5).status==200)
check('postgres',lambda:sql('SELECT 1')=='1')
check('db_connections',lambda:float(sql("SELECT count(*)::numeric/current_setting('max_connections')::int FROM pg_stat_activity"))<0.8)
check('disk_free',lambda:os.statvfs(a.output.parent).f_bavail*os.statvfs(a.output.parent).f_frsize/1024**3>=a.min_disk_free_gb)
def backup_check():
    manifest=json.loads((a.backup/'manifest.json').read_text())
    age=(datetime.now(timezone.utc).timestamp()-(a.backup/'manifest.json').stat().st_mtime)/3600
    return age<=a.max_backup_age_hours and all((a.backup/n).is_file() and (a.backup/n).stat().st_size==v['bytes'] and hashlib.file_digest((a.backup/n).open('rb'),'sha256').hexdigest()==v['sha256'] for n,v in manifest['files'].items())
check('backup_fresh_and_complete',backup_check)
check('cron_failures',lambda:sql('SELECT count(*) FROM ir_cron WHERE active AND failure_count>0')=='0')
check('budget_orphan_sources',lambda:sql('SELECT count(*) FROM erp_budget_move m LEFT JOIN erp_budget_control c ON c.id=m.control_id WHERE c.id IS NULL OR c.company_id<>m.company_id OR c.organization_id<>m.organization_id')=='0')
check('budget_negative_capacity',lambda:sql("SELECT count(*) FROM (SELECT c.id FROM erp_budget_control c JOIN erp_budget_period p ON p.id=c.period_id LEFT JOIN erp_budget_kpi k ON k.id=c.kpi_id JOIN res_company company ON company.id=c.company_id JOIN res_currency r ON r.id=company.currency_id LEFT JOIN erp_budget_move m ON m.control_id=c.id WHERE c.active AND NOT (c.level='analytic' AND p.control_level='analytic_kpi' AND COALESCE(k.advance_reservation,false)) GROUP BY c.id,r.rounding HAVING c.amount-COALESCE(sum(m.amount),0)<-r.rounding/2) invalid")== '0')
check('posted_move_balance',lambda:sql("SELECT count(*) FROM (SELECT m.id FROM account_move m JOIN account_move_line l ON l.move_id=m.id JOIN res_company c ON c.id=m.company_id JOIN res_currency r ON r.id=c.currency_id WHERE m.state='posted' GROUP BY m.id,r.rounding HAVING abs(sum(l.balance))>=r.rounding/2) invalid")=='0')
def error_logs():
    logs=subprocess.run(['docker','logs','--since','5m','erp-readiness20-app-1'],capture_output=True,text=True,timeout=10)
    if logs.returncode:
        return False
    return not re.search(r'Traceback \(most recent call last\)|maximum number of tries reached|ERROR .*cron|READINESS_EXPECTED_CRON_FAILURE',logs.stdout+logs.stderr)
check('recent_error_logs',error_logs)
try:
    filestore_bytes=subprocess.check_output(['docker','exec','erp-readiness20-app-1','du','-sb','/var/lib/odoo/filestore'],text=True,stderr=subprocess.DEVNULL,timeout=10).split()[0]
except Exception:
    filestore_bytes=None
result={'timestamp':datetime.now(timezone.utc).isoformat(),'database':a.database,'checks':checks,'alerts':[n for n,v in checks.items() if v['status']=='FAIL'],'filestore_bytes':filestore_bytes}
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'alerts':result['alerts'],'checks':len(checks),'output':str(a.output)}))
raise SystemExit(2 if result['alerts'] else 0)
