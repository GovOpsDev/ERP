#!/usr/bin/env python3
"""DATA MIGRATION FIX: read-only fingerprints of original business columns.

This reports differences; it never guesses mappings or changes business data.
Use --baseline to reuse the original columns when inspecting an upgraded DB.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

p=argparse.ArgumentParser()
p.add_argument('--database',required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--baseline',type=Path)
a=p.parse_args()
def query(sql):
    return subprocess.check_output(['docker','exec','erp-readiness20-db-1','psql','-U','odoo','-d',a.database,'-At','-c',sql],text=True)
if a.baseline:
    original=json.loads(a.baseline.read_text())
    columns=original['columns']
else:
    tables=query("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE 'erp_%' OR tablename LIKE 'account_%' OR tablename LIKE 'purchase_%' OR tablename LIKE 'stock_%' OR tablename LIKE 'hr_%' OR tablename IN ('res_company','res_users','res_groups_users_rel','ir_attachment')) ORDER BY tablename").splitlines()
    columns={t:query("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='%s' ORDER BY ordinal_position"%t).splitlines() for t in tables}
result={'database':a.database,'columns':columns,'tables':{}}
for table,cols in columns.items():
    fields=', '.join('"'+x+'"' for x in cols)
    # Sort complete JSON rows for relation tables that have no id column.
    data=query('SELECT row_to_json(t)::text FROM (SELECT '+fields+' FROM "'+table+'") t ORDER BY row_to_json(t)::text')
    result['tables'][table]={'rows':len(data.splitlines()),'sha256':hashlib.sha256(data.encode()).hexdigest()}
financial={
 'budget_controls':"SELECT company_id,period_id,level,sum(amount)::text FROM erp_budget_control GROUP BY 1,2,3 ORDER BY 1,2,3",
 'budget_ledger':"SELECT company_id,control_id,move_type,sum(amount)::text FROM erp_budget_move GROUP BY 1,2,3 ORDER BY 1,2,3",
 'posted_gl':"SELECT m.company_id,l.account_id,sum(l.debit)::text,sum(l.credit)::text,sum(l.balance)::text FROM account_move_line l JOIN account_move m ON m.id=l.move_id WHERE m.state='posted' GROUP BY 1,2 ORDER BY 1,2",
 'asset_acquisition':"SELECT company_id,count(*),sum(purchase_value)::text FROM erp_asset_asset GROUP BY 1 ORDER BY 1",
 'asset_engine':"SELECT company_id,count(*),sum(purchase_value)::text,sum(value_depreciated)::text,sum(value_residual)::text FROM account_asset GROUP BY 1 ORDER BY 1",
}
result['financial']={k:query(v).splitlines() for k,v in financial.items()}
if a.baseline:
    result['changed_tables']=[k for k,v in result['tables'].items() if v!=original['tables'][k]]
    result['financial_differences']=[k for k,v in result['financial'].items() if v!=original['financial'][k]]
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'database':a.database,'tables':len(columns),'changed_tables':result.get('changed_tables'), 'financial_differences':result.get('financial_differences')},indent=2))
