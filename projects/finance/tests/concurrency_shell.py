# Run only on an isolated clone of the documented seeded upgrade fixture.
# This script modifies and commits synthetic users and bills; never run on production.
import threading
from odoo import api
reg = env.registry
request = env['erp.procurement.request'].browse(1)
po = env['purchase.order'].browse(1)
first_bill = env['account.move'].browse(1)
user = env['res.users'].search([('login', '=', 'finance_upgrade_user')], limit=1)
user.write({'group_ids': [(4, env.ref('account.group_account_invoice').id)]})
first_bill.invoice_line_ids.write({'quantity': 0.8, 'price_unit': 50, 'product_uom_id': po.order_line.uom_id.id, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(po.order_line.erp_budget_analytic_id.id): 100}})
second_bill = first_bill.copy()
second_bill.invoice_line_ids.write({'purchase_line_id': po.order_line.id, 'product_uom_id': po.order_line.uom_id.id, 'quantity': 0.8, 'price_unit': 50, 'tax_ids': [(5, 0, 0)], 'analytic_distribution': {str(po.order_line.erp_budget_analytic_id.id): 100}})
ids, uid, company_id = [first_bill.id, second_bill.id], user.id, po.company_id.id
env.cr.commit()
ready = threading.Event()
release = threading.Event()
results = {}
def worker_first():
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['account.move'].browse(ids[0]).action_post()
            ready.set()
            if not release.wait(20):
                raise RuntimeError('second did not start')
            cr.commit()
        results['A'] = 'committed'
    except Exception as exc:
        results['A'] = type(exc).__name__
        print('FIRST_ERROR', str(exc))
        ready.set()
def worker_second():
    ready.wait(20)
    try:
        with reg.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            e['account.move'].browse(ids[1]).action_post()
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__
        print('SECOND_ERROR', str(exc))
a = threading.Thread(target=worker_first)
b = threading.Thread(target=worker_second)
a.start(); b.start()
ready.wait(20)
import time
time.sleep(1)
release.set()
a.join(30); b.join(30)
with reg.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    moves = e['erp.budget.move'].sudo().search([('family_key', '=', 'erp.procurement.request.line:1')])
    control = po.order_line.erp_request_line_id._budget_controls()[:1].id
    rows = moves.filtered(lambda m: m.control_id.id == control)
    states = e['account.move'].browse(ids).mapped('state')
    total = sum(rows.mapped('amount'))
    print('BILL_RACE', results, states, total)
    assert results.get('A') == 'committed' and results.get('B') in ('SerializationFailure', 'ValidationError')
    assert sorted(states) == ['draft', 'posted'] and total == 50
