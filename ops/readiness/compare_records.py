#!/usr/bin/env python3
"""Read-only original-row comparison in one repeatable-read snapshot per database.

Caller quiesces writers for cross-database acceptance. Report changes, never infer
historical mappings. Sensitive credential columns are redacted from the report.
"""
import argparse,json,re,subprocess
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--columns',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
assert all(re.fullmatch(r'erp_[a-z0-9_]+',d) for d in [a.before,a.after])
columns=json.loads(a.columns.read_text())['columns']
statements=['BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY']
for table,cols in columns.items():
    assert all(re.fullmatch(r'[a-z_][a-z0-9_]*',x) for x in [table,*cols])
    names=','.join('"'+c+'"' for c in cols)
    statements.append(f"SELECT json_build_object('table','{table}','rows',COALESCE(json_agg(row_to_json(t)),'[]'::json)) FROM (SELECT {names} FROM \"{table}\") t")
statements.append('COMMIT')
def snapshot(db):
    output=subprocess.check_output(['docker','exec','-i','erp-readiness20-db-1','psql','-X','-qAt','-v','ON_ERROR_STOP=1','-U','odoo','-d',db],input=';\n'.join(statements)+';\n',text=True)
    rows=[json.loads(line) for line in output.splitlines() if line.startswith('{')]
    assert len(rows)==len(columns)
    return {r['table']:r['rows'] for r in rows}
before=snapshot(a.before);after=snapshot(a.after);changes={}
def safe(field,value):
    return '<redacted>' if re.search(r'password|secret|token|totp|oauth',field,re.I) else value
for table,cols in columns.items():
    old,new=before[table],after[table]
    if 'id' in cols:
        left={r['id']:r for r in old};right={r['id']:r for r in new};modified=[]
        for key in left.keys() & right.keys():
            diff={f:{'before':safe(f,left[key][f]),'after':safe(f,right[key][f])} for f in cols if left[key][f]!=right[key][f]}
            if diff:modified.append({'id':key,'changes':diff})
        item={'original_row_changes':modified,'removed_ids':sorted(left.keys()-right.keys()),'new_ids':sorted(right.keys()-left.keys())}
        changed=bool(modified or item['removed_ids'] or item['new_ids'])
    else:
        left=Counter(json.dumps(r,sort_keys=True,default=str) for r in old);right=Counter(json.dumps(r,sort_keys=True,default=str) for r in new)
        item={'removed_relations':[json.loads(r) for r in sorted((left-right).elements())],'new_relations':[json.loads(r) for r in sorted((right-left).elements())]};changed=left!=right
    if changed:changes[table]={'before_count':len(old),'after_count':len(new),**item}
result={'before':a.before,'after':a.after,'tables':len(columns),'changes':changes,'scope':'original columns; separate read-only repeatable-read snapshots; writers must be quiesced'}
a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'tables':len(columns),'changed_tables':list(changes),'output':str(a.output)}))
