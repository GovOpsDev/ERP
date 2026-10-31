# Only a disposable clone of the acquisition milestone; commits synthetic configuration.
import threading
import time
from odoo import api
registry = env.registry
acquisition = env['erp.asset.asset'].search([], limit=1)
assert acquisition and not acquisition.engine_asset_id
company, account = acquisition.company_id, acquisition.source_line_id.account_id
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('erp_asset.group_asset_manager').id)]})
journal = env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
if not journal:
    journal = env['account.journal'].create({'name': 'Race journal', 'code': 'RACE', 'type': 'general', 'company_id': company.id})
profile = env['account.asset.profile'].with_company(company).create({'name': 'Race profile', 'company_id': company.id, 'account_asset_id': account.id, 'account_depreciation_id': account.id, 'account_expense_depreciation_id': account.id, 'journal_id': journal.id, 'method_time': 'year', 'method_number': 3, 'method_period': 'year', 'open_asset': False})
account.asset_profile_id = False
acquisition.profile_id.oca_profile_id = profile
asset_id, profile_id, uid, company_id = acquisition.id, profile.id, user.id, company.id
env.cr.commit()
ready, release = threading.Event(), threading.Event()
results = {}
def first():
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['erp.asset.asset'].browse(asset_id).action_create_depreciation_asset()
            ready.set()
            assert release.wait(20)
            cr.commit()
        results['link'] = 'committed'
    except Exception as exc:
        results['link'] = type(exc).__name__
        print('LINK_ERROR', str(exc))
        ready.set()
def second():
    assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['account.asset.profile'].browse(profile_id).write({'method_number': 9})
            cr.commit()
        results['edit'] = 'committed'
    except Exception as exc:
        results['edit'] = type(exc).__name__
        print('EDIT_ERROR', str(exc))
a, b = threading.Thread(target=first), threading.Thread(target=second)
a.start(); b.start()
assert ready.wait(20)
time.sleep(1)
release.set()
a.join(30); b.join(30)
assert not a.is_alive() and not b.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    linked = e['account.asset'].sudo().search([('erp_acquisition_id', '=', asset_id)])
    method = e['account.asset.profile'].sudo().browse(profile_id).method_number
    print('PROFILE_LINK_RACE', results, len(linked), method)
    assert results.get('link') == 'committed' and results.get('edit') in ('SerializationFailure', 'UserError')
    assert len(linked) == 1 and method == 3
