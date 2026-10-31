# Isolated synthetic test database only. Commits fixture and competing approvals.
import threading
import time
import unittest
from odoo import api
from odoo.addons.erp_procurement.tests.test_government import TestGovernmentProcurement
class Fixture(unittest.TestCase):
    make_request = TestGovernmentProcurement.make_request
    make_po = TestGovernmentProcurement.make_po
fixture = Fixture()
fixture.env = env
fixture.company = fixture.env['res.company'].create({'name': 'Procurement Company'})
fixture.env['stock.warehouse'].create({'name': 'Race warehouse', 'code': 'RACE', 'company_id': fixture.company.id})
fixture.unit = fixture.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': fixture.company.id})
fixture.user = fixture.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': fixture.company.id, 'company_ids': [(6, 0, [fixture.company.id])], 'group_ids': [(6, 0, [fixture.env.ref('erp_procurement.group_procurement_manager').id])]})
fixture.env['erp.organization.assignment'].create({'user_id': fixture.user.id, 'unit_id': fixture.unit.id})
fixture.env['erp.procurement.tier'].create({'name': 'Standard review', 'company_id': fixture.company.id, 'reviewer_id': fixture.user.id, 'minimum_amount': 0, 'sequence': 10})
fixture.group = fixture.env['erp.budget.fund.group'].create({'name': 'PR group', 'company_id': fixture.company.id})
fixture.fund = fixture.env['erp.budget.fund'].create({'name': 'PR fund', 'company_id': fixture.company.id, 'group_id': fixture.group.id})
fixture.period = fixture.env['erp.budget.period'].create({'name': 'PR period', 'company_id': fixture.company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
plan = fixture.env['account.analytic.plan'].create({'name': 'PR plan'})
fixture.analytic = fixture.env['account.analytic.account'].create({'name': 'PR analytic', 'plan_id': plan.id, 'company_id': fixture.company.id})
fixture.account = fixture.env['account.account'].create({'name': 'PR expense', 'code': 'PR100', 'account_type': 'expense', 'company_ids': [(6, 0, [fixture.company.id])]})
fixture.product = fixture.env['product.product'].create({'name': 'Test service', 'type': 'service', 'purchase_ok': True})
fixture.product.with_company(fixture.company).product_tmpl_id.property_account_expense_id = fixture.account
fixture.vendor = fixture.env['res.partner'].create({'name': 'Test vendor', 'supplier_rank': 1})
env = fixture.env(user=fixture.user, context={'allowed_company_ids': [fixture.company.id]})
vals = {'company_id': fixture.company.id, 'period_id': fixture.period.id, 'organization_id': fixture.unit.id, 'analytic_id': fixture.analytic.id, 'amount': 100}
fixture.ac = fixture.env['erp.budget.control'].create(dict(vals, name='Analytic limit', level='analytic'))
fixture.fc = fixture.env['erp.budget.control'].create(dict(vals, name='Fund limit', level='fund', fund_id=fixture.fund.id))
(fixture.ac | fixture.fc).action_open()
fixture.test_env = env
fixture.test_env['erp.procurement.tier'].create({'name': 'PO tier', 'company_id': fixture.company.id, 'reviewer_id': fixture.user.id, 'kind': 'purchase'})
request = fixture.make_request(80)
request.action_submit()
request.action_approve()
po = fixture.make_po(request, 60)
po.button_confirm()
uid, company_id, po_id = fixture.user.id, fixture.company.id, po.id
registry = env.registry
env.cr.commit()
ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
results = {}
def worker(first):
    if not first:
        assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            if not first:
                cr.execute('SELECT id FROM purchase_order WHERE id=%s', [po_id])
                cr.fetchone()
                snapshot.set()
            e['purchase.order'].browse(po_id).action_approve_tier()
            if first:
                ready.set()
                assert release.wait(20)
            cr.commit()
        results[first] = 'committed'
    except Exception as exc:
        results[first] = type(exc).__name__
        ready.set() if first else snapshot.set()
threads = [threading.Thread(target=worker, args=(first,)) for first in (True, False)]
for thread in threads:
    thread.start()
assert snapshot.wait(20)
time.sleep(.3)
release.set()
for thread in threads:
    thread.join(30)
    assert not thread.is_alive()
assert results == {True: 'committed', False: 'SerializationFailure'}, results
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    current = e['purchase.order'].browse(po_id)
    current.action_approve_tier()
    assert current.state == 'purchase' and len(current.erp_review_ids) == 1
    assert sum(e['erp.budget.move'].sudo().search([('control_id', '=', fixture.ac.id)]).mapped('amount')) == 60
    cr.commit()
print('PURCHASE_TIER_CONCURRENCY_PASSED', results)
