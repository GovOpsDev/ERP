# Synthetic data only: run against a disposable clone of the Contract upgrade fixture.
import threading
from odoo import api
registry = env.registry
po = env['purchase.order'].browse(1)
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('erp_inventory.group_acceptance_manager').id)]})
company_id, uid = po.company_id.id, user.id
e = env(user=user, context={'allowed_company_ids': [company_id]})
line = po.order_line[:1]
assert po.state in ('purchase', 'done') and line.product_qty > 0
records = e['erp.inventory.acceptance'].create([{'company_id': company_id, 'organization_id': po.erp_request_organization_id.id, 'purchase_order_id': po.id, 'line_ids': [(0, 0, {'purchase_line_id': line.id, 'quantity': line.product_qty * 0.8})]} for _ in range(2)])
ids = records.ids
env.cr.commit()
ready, release = threading.Event(), threading.Event()
results = {}
def first():
    try:
        with registry.cursor() as cr:
            e1 = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e1['erp.inventory.acceptance'].browse(ids[0]).action_accept()
            ready.set()
            assert release.wait(20)
            cr.commit()
        results['first'] = 'committed'
    except Exception as exc:
        results['first'] = type(exc).__name__
        ready.set()
def second():
    assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e2 = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e2['erp.inventory.acceptance'].browse(ids[1]).action_accept()
            cr.commit()
        results['second'] = 'committed'
    except Exception as exc:
        results['second'] = type(exc).__name__
a, b = threading.Thread(target=first), threading.Thread(target=second)
a.start(); b.start()
assert ready.wait(20)
import time
time.sleep(1)
release.set()
a.join(30); b.join(30)
assert not a.is_alive() and not b.is_alive()
with registry.cursor() as cr:
    check = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    states = check['erp.inventory.acceptance'].browse(ids).mapped('state')
    total = sum(check['erp.inventory.acceptance.line'].sudo().search([('purchase_line_id', '=', line.id), ('acceptance_id.state', '=', 'accept')]).mapped('quantity'))
    print('ACCEPTANCE_RACE', results, states, total)
    assert results.get('first') == 'committed' and results.get('second') in ('SerializationFailure', 'ValidationError')
    assert sorted(states) == ['accept', 'draft'] and total <= line.product_qty
