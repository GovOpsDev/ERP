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

fixture.user.write({'group_ids': [(4, fixture.env.ref('erp_inventory.group_stock_request_manager').id)]})
fixture.product.write({'type': 'consu', 'is_storable': True})
warehouse = fixture.env['stock.warehouse'].search([('company_id', '=', fixture.company.id)], limit=1)
location = fixture.env['stock.location'].create({'name': 'Race destination', 'usage': 'internal', 'company_id': fixture.company.id, 'location_id': warehouse.view_location_id.id})
route = fixture.env['stock.route'].create({'name': 'Race stock supply', 'company_id': fixture.company.id})
fixture.env['stock.rule'].create({'name': 'Race stock supply', 'company_id': fixture.company.id, 'route_id': route.id, 'action': 'pull', 'location_dest_from_rule': True, 'location_src_id': warehouse.lot_stock_id.id, 'location_dest_id': location.id, 'picking_type_id': warehouse.int_type_id.id, 'procure_method': 'make_to_stock'})
fixture.env['stock.quant']._update_available_quantity(fixture.product, warehouse.lot_stock_id, 10)
request = fixture.test_env['erp.inventory.request'].create({'company_id': fixture.company.id, 'organization_id': fixture.unit.id, 'warehouse_id': warehouse.id, 'location_id': location.id, 'line_ids': [(0, 0, {'product_id': fixture.product.id, 'quantity': 4, 'route_id': route.id, 'fund_id': fixture.fund.id, 'analytic_id': fixture.analytic.id})]})
request.action_submit()
uid, company_id, request_id = fixture.user.id, fixture.company.id, request.id
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
                cr.execute('SELECT id FROM erp_inventory_request WHERE id=%s', [request_id])
                cr.fetchone()
                snapshot.set()
            e['erp.inventory.request'].browse(request_id).action_approve()
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
    current = e['erp.inventory.request'].browse(request_id)
    current.action_approve()
    assert len(current.line_ids.move_ids) == 1 and current.state == 'open'
    assert not e['erp.budget.move'].sudo().search_count([('control_id', '=', fixture.ac.id)])
    cr.commit()
print('STOCK_REQUEST_CONCURRENCY_PASSED', results)
