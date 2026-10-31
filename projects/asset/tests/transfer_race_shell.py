# Run only against a disposable clone: this fixture commits synthetic accounting records.
import threading
import time
from odoo import api, fields

registry = env.registry
acquisition = env['erp.asset.asset'].search([('engine_asset_id', '=', False)], limit=1)
assert acquisition
company = acquisition.company_id
account = acquisition.source_line_id.account_id
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
assert user
user.write({'group_ids': [(4, env.ref('erp_asset.group_asset_manager').id), (4, env.ref('account.group_account_manager').id)]})
journal = env['account.journal'].search([('company_id', '=', company.id), ('type', '=', 'general')], limit=1)
if not journal:
    journal = env['account.journal'].create({'name': 'Transfer race', 'code': 'TRAC', 'type': 'general', 'company_id': company.id})
profile = env['account.asset.profile'].with_company(company).create({'name': 'Transfer AUC race', 'company_id': company.id, 'account_asset_id': account.id, 'account_depreciation_id': account.id, 'account_expense_depreciation_id': account.id, 'journal_id': journal.id, 'method_time': 'year', 'method_number': 0, 'method_period': 'year', 'open_asset': False})
account.asset_profile_id = False
acquisition.profile_id.oca_profile_id = profile
uid, company_id, acquisition_id, profile_id, journal_id = user.id, company.id, acquisition.id, profile.id, journal.id
e = api.Environment(env.cr, uid, {'allowed_company_ids': [company_id]})
a = e['erp.asset.asset'].browse(acquisition_id)
a.action_create_depreciation_asset()
source = a.engine_asset_id
source.validate()
source_id, amount = source.id, source.purchase_value
env.cr.commit()
ready, release = threading.Event(), threading.Event()
results = {}
def run(label):
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            if label == 'second':
                assert ready.wait(60)
            wiz = e['account.asset.transfer'].with_context(active_ids=[source_id]).create({'company_id': company_id, 'transfer_journal_id': journal_id, 'date_transfer': fields.Date.today(), 'from_asset_ids': [(6, 0, [source_id])], 'to_asset_ids': [(0, 0, {'asset_name': label, 'asset_profile_id': profile_id, 'quantity': 1, 'price_unit': amount})]})
            wiz.transfer()
            if label == 'first':
                ready.set()
                assert release.wait(60)
            cr.commit()
        results[label] = 'committed'
    except Exception as exc:
        results[label] = type(exc).__name__
        if label == 'first':
            ready.set()
first = threading.Thread(target=run, args=('first',))
second = threading.Thread(target=run, args=('second',))
first.start(); second.start()
assert ready.wait(60)
time.sleep(1)
release.set()
first.join(70); second.join(70)
assert not first.is_alive() and not second.is_alive()
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    history = e['erp.asset.transfer.history'].search([('source_ids', 'in', [source_id])])
    print('TRANSFER_RACE', results, len(history), sum(history.destination_ids.mapped('purchase_value')), amount)
    assert results.get('first') == 'committed' and results.get('second') in ('SerializationFailure', 'ValidationError', 'UserError')
    assert len(history) == 1 and len(history.destination_ids) == 1 and history.destination_ids.purchase_value == amount
