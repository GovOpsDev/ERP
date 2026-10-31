"""Run with Odoo shell on the local reference DB after installing erp_dashboard_th.

Read-only assertions: preserve stored workbook, English output, business records,
formula operations, company context and the existing trial user's permissions.
"""
import hashlib
import json
import re

xmlid = 'spreadsheet_dashboard_stock_account.spreadsheet_dashboard_warehouse_metrics'
dashboard = env.ref(xmlid)
raw = dashboard.with_context(lang='en_US').spreadsheet_data
stored_digest = hashlib.sha256(raw.encode()).hexdigest()
en_payload = json.loads(dashboard.with_context(lang='en_US')._get_serialized_readonly_dashboard())
th_payload = json.loads(dashboard.with_context(lang='th_TH')._get_serialized_readonly_dashboard())
assert en_payload['snapshot']['sheets'] == json.loads(raw)['sheets']
assert th_payload['snapshot']['sheets'][0]['figures'][0]['data']['title']['text'] == 'สัดส่วนมูลค่าสินค้าที่จองไว้'
assert dashboard.with_context(lang='th_TH').name == 'ภาพรวมคลังสินค้า'

# Ignore presentation strings only: every formula's operations/references, numeric
# constants, layout and technical keys must remain identical across languages.
changed = []
def compare(left, right, path=()):
    assert type(left) is type(right), path
    if isinstance(left, dict):
        assert left.keys() == right.keys(), path
        for key in left: compare(left[key], right[key], path + (key,))
    elif isinstance(left, list):
        assert len(left) == len(right), path
        for i, (a, b) in enumerate(zip(left, right)): compare(a, b, path + (i,))
    elif left != right:
        assert isinstance(left, str), (path, left, right)
        if left.startswith('='):
            assert re.sub(r'"(?:[^"]|"")*"', '""', left) == re.sub(r'"(?:[^"]|"")*"', '""', right), path
            expected = left.replace('"No data"', '"ไม่มีข้อมูล"').replace('" out of "', '" จาก "')
            assert right == expected, path
        else:
            assert path[-1] in {'text', 'title', 'label'} or 'cells' in path, path
        changed.append('/'.join(map(str,path)))
compare(en_payload['snapshot']['sheets'], th_payload['snapshot']['sheets'], ('sheets',))
assert any('cells' in p for p in changed) and any('figures' in p for p in changed)
assert hashlib.sha256(dashboard.with_context(lang='en_US').spreadsheet_data.encode()).hexdigest() == stored_digest
sample = dashboard.with_context(lang='th_TH')._get_sample_dashboard()
assert sample['sheets'][0]['figures'][0]['data']['title']['text'] == 'สัดส่วนมูลค่าสินค้าที่จองไว้'
other = env['spreadsheet.dashboard'].search([('id', '!=', dashboard.id)], limit=1)
if other:
    assert not other.with_context(lang='th_TH')._uses_thai_warehouse_labels()

trial = env['res.users'].search([('login', '=', 'trial_demo')], limit=1)
assert trial and not trial.has_group('base.group_system') and not trial.has_group('base.group_erp_manager')
scoped_reads = []
for company in trial.company_ids:
    user_dashboard = dashboard.with_user(trial).with_context(lang='th_TH', allowed_company_ids=[company.id])
    if user_dashboard.has_access('read'):
        assert not user_dashboard.env.su
        data = json.loads(user_dashboard._get_serialized_readonly_dashboard())
        assert data['snapshot']['sheets'] == th_payload['snapshot']['sheets']
        scoped_reads.append(company.id)
assert scoped_reads
print('DASHBOARD_TH_PASS ' + json.dumps({'translated_display_fields':len(changed), 'english_source_preserved':True, 'formula_operations_preserved':True, 'stored_workbook_sha256':stored_digest, 'stored_workbook_unchanged':True, 'sample_dashboard':'PASS', 'trial_company_contexts':scoped_reads, 'trial_privileges_unchanged':True, 'other_dashboard_untouched':bool(other)}))
