# Isolated asset-upgrade clone only: commits synthetic test documents.
import threading
import time
from odoo import api
registry = env.registry
po = env['purchase.order'].browse(1)
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
company_id, uid = po.company_id.id, user.id
user.write({'group_ids': [(4, env.ref('erp_inventory.group_acceptance_manager').id), (4, env.ref('account.group_account_invoice').id), (4, env.ref('erp_asset.group_asset_manager').id)]})
e = env(user=user, context={'allowed_company_ids': [company_id]})
wa = e['erp.inventory.acceptance'].create({'company_id': company_id, 'organization_id': po.erp_request_organization_id.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': po.order_line[:1].id, 'quantity': 0.2})]})
wa.action_accept()
old = e['account.move'].search([('id', '=', 126)])
bill = old.copy({'invoice_date': '2026-06-10', 'date': '2026-06-10'})
bill.invoice_line_ids.filtered('product_id').write({'purchase_line_id': po.order_line[:1].id, 'product_id': po.order_line[:1].product_id.id, 'product_uom_id': po.order_line[:1].uom_id.id, 'price_unit': po.order_line[:1].price_unit, 'quantity': 0.2})
bill.erp_acceptance_id = wa
bill_id = bill.id
profile_id = e['erp.asset.profile'].search([('company_id', '=', company_id), ('account_id', '=', po.order_line[:1].erp_budget_account_id.id), ('active', '=', True)], limit=1).id
assert profile_id
env.cr.commit()
ready, release = threading.Event(), threading.Event()
results = {}
def first():
    try:
        with registry.cursor() as cr:
            e1 = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e1['account.move'].browse(bill_id).action_post()
            ready.set()
            assert release.wait(20)
            cr.commit()
        results['first'] = 'committed'
    except Exception as exc:
        results['first'] = type(exc).__name__
        print('FIRST_ERROR', str(exc))
        ready.set()
def second():
    assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e2 = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e2['erp.asset.profile'].browse(profile_id).write({'active': False})
            cr.commit()
        results['second'] = 'committed'
    except Exception as exc:
        results['second'] = type(exc).__name__
        print('SECOND_ERROR', str(exc))
a, b = threading.Thread(target=first), threading.Thread(target=second)
a.start(); b.start()
assert ready.wait(20)
time.sleep(1)
release.set()
a.join(30); b.join(30)
assert not a.is_alive() and not b.is_alive()
with registry.cursor() as cr:
    check = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    count = check['erp.asset.asset'].sudo().search_count([('bill_id', '=', bill_id)])
    state = check['account.move'].browse(bill_id).state
    active = check['erp.asset.profile'].browse(profile_id).active
    print('PROFILE_POST_RACE', results, state, count, active)
    assert results.get('first') == 'committed' and results.get('second') in ('SerializationFailure', 'UserError')
    assert state == 'posted' and count == 1 and active
