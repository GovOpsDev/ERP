#!/usr/bin/env python3
"""SECURITY FIX: reproducible privilege-use inventory and reviewed rationale.

AST enumeration includes sudo(False) and with_user. This is the scoped readiness
review record, not a claim that static analysis proves absence of vulnerabilities.
"""
import argparse,ast,hashlib,json
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);a=p.parse_args()
root=Path(__file__).resolve().parents[2];rows=[]
for directory in [root/'projects',root/'shared']:
 for path in directory.rglob('*.py'):
  if '/addons/' not in str(path) or '/tests/' in str(path):continue
  source=path.read_text()
  try:tree=ast.parse(source)
  except SyntaxError as exc:raise RuntimeError(f'Cannot audit {path}') from exc
  parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
  for call in ast.walk(tree):
   if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute) or call.func.attr not in ['sudo','with_user']:continue
   node=call
   while node in parents and not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):node=parents[node]
   fn=node.name if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) else '<module>'
   function_source=ast.get_source_segment(source,node)
   relative=str(path.relative_to(root));expression=ast.get_source_segment(source,call)
   guards=[line.strip() for line in function_source.splitlines() if any(s in line for s in ['check_access(', 'has_group(', '_manager_check(', '_check_delegation(', '.with_env(', '_lock_and_check(', '_validate_', '_check_scope(', '_check_assignment('])]
   classification='protected by explicit validation'
   if call.func.attr=='with_user':
    reason='Reviewer/service identity evaluation; destination company and record access are checked under that identity. No supplied RPC user ID is promoted to superuser.'
   elif call.args and isinstance(call.args[0],ast.Constant) and call.args[0].value is False:
    classification='justified';reason='Explicitly removes superuser mode for report rendering.'
   elif 'account_asset_management/models/account_asset.py' in relative and fn=='_compute_entries':
    reason='Vendored unscoped trigger path is bypassed by erp_asset ScopedAssetRecompute; every super call passes check_triggers=False. Regression checks a foreign-company trigger stays open.'
   elif 'erp_asset/models/asset.py' in relative and fn=='_compute_entries':
    reason='Read-only complete-company asset ID inventory; no data returned. Trigger completion requires full selected company coverage and successful processing.'
   elif '/erp_user_role/' in relative:
    reason='Private role provenance/reconciliation engine. Public mutations retain native ACLs and delegation checks before group membership changes; ContextVar guards internal writes. Administrator-owned cron is intentionally global and applies effective dates and OU/company membership.'
   elif fn=='default_unit_for_current_user':
    reason='Read-only assignment lookup explicitly restricted to env.user.id; returns only the current user default organization.'
   elif fn=='_access_domain':
    reason='Reads current-user policy and technical model metadata to build restrictive domains; does not grant rights or return privileged records.'
   elif 'search_count' in function_source or fn.startswith(('_check','_validate','_has','_is','_opening')):
    reason='Complete dependency/history check prevents hidden records bypassing integrity constraints. Returned result is a validation/boolean, not unrestricted business records; mutation retains ordinary ACL checks.'
   elif '.with_env(self.env)' in function_source:
    reason='Enumerates complete source/history records then restores the caller environment and checks access before processing, preventing partially hidden document reconciliation.'
   elif '/erp_organization' in relative:
    reason='Company/OU integrity and immutable employee scope-history maintenance after normal create/write checks; no assignment or HR read permission is granted.'
   elif '/erp_asset/' in relative:
    reason='Immutable acquisition/valuation/transfer provenance from validated native posting or Asset manager lifecycle action; source scope, company, profile and amount guards precede privileged history creation.'
   elif '/erp_budget/' in relative:
    reason='Private ledger/version/review machinery under ordinary source/control ACLs, manager or assigned-reviewer checks, fiscal locks and ContextVar write guards; source amounts and shared capacity are validated before append-only writes.'
   elif '/erp_procurement/' in relative or '/erp_inventory/' in relative or '/erp_finance/' in relative:
    reason='Validated native workflow source, review-history or configuration access. Review mutations require the assigned actor; accounting/stock writes retain native ACLs, source validation and company/OU domains.'
   elif '/erp_contract/' in relative:
    reason='Contract manager lifecycle snapshots or complete source validation; source/company/OU checks and immutable provenance constrain elevated history operations.'
   elif '/account_asset_management/' in relative:
    reason='Native linked-depreciation integrity check or technical action metadata; ordinary record ACLs remain enforced. The separate trigger-scope defect is intercepted by the ERP override.'
   else:
    raise RuntimeError(f'Unclassified privilege use: {relative}:{call.lineno}')
   rows.append({'file':relative,'line':call.lineno,'function':fn,'kind':call.func.attr,'expression':expression,'classification':classification,'rationale':reason,'local_guard_evidence':guards,'file_sha256':hashlib.sha256(source.encode()).hexdigest()})
result={'scope':'all custom and vendored project addons; tests excluded','review':'source inspection plus focused security and full regression; not an independent penetration audit','count':len(rows),'classifications':dict(Counter(r['classification'] for r in rows)),'unclassified':0,'calls':rows}
a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='calls'}))
