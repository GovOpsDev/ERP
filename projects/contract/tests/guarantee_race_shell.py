# Run only on an isolated upgraded test DB; commits synthetic concurrency evidence.
import threading
import time
import unittest
from odoo import api
from odoo.exceptions import UserError, ValidationError
from odoo.addons.erp_contract.tests.test_guarantee import TestPurchaseGuarantee
class Fixture(unittest.TestCase):
    make_request = TestPurchaseGuarantee.make_request
    make_po = TestPurchaseGuarantee.make_po
    setup_guarantee = TestPurchaseGuarantee.setup_guarantee
    pay_guarantee = TestPurchaseGuarantee.pay_guarantee
fixture = Fixture()
fixture.env = env
fixture.company = fixture.env['res.company'].create({'name': 'Procurement Company'})
fixture.unit = fixture.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': fixture.company.id})
fixture.user = fixture.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': fixture.company.id, 'company_ids': [(6, 0, [fixture.company.id])], 'group_ids': [(6, 0, [fixture.env.ref('erp_procurement.group_procurement_manager').id])]})
fixture.user.write({'group_ids': [(4, fixture.env.ref('account.group_account_invoice').id), (4, fixture.env.ref('erp_contract.group_contract_manager').id)]})
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

env = fixture.env
warehouse = env['stock.warehouse'].create({'name': 'Guarantee race warehouse', 'code': 'GRW', 'company_id': fixture.company.id})
fixture.test_env = fixture.test_env(context=dict(fixture.test_env.context, default_picking_type_id=warehouse.in_type_id.id))
guarantee = fixture.setup_guarantee()
receipt = fixture.test_env['account.move'].browse(guarantee.action_create_receipt()['res_id'])
receipt.action_post()
fixture.pay_guarantee(receipt)
uid, company_id, guarantee_id, receipt_id = fixture.user.id, fixture.company.id, guarantee.id, receipt.id
registry = env.registry
env.cr.commit()
ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
results = {}
def run_first():
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            result = e['erp.contract.guarantee'].browse(guarantee_id).action_create_return()
            results['return_id'] = result['res_id']
            ready.set()
            assert release.wait(20)
            cr.commit()
        results['A'] = 'committed'
    except Exception as exc:
        results['A'] = type(exc).__name__
        ready.set()
def run_second():
    assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            cr.execute('SELECT amount FROM erp_contract_guarantee WHERE id=%s', [guarantee_id])
            cr.fetchone()
            snapshot.set()
            e['erp.contract.guarantee'].browse(guarantee_id).action_create_return()
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__
        snapshot.set()
threads = [threading.Thread(target=run_first), threading.Thread(target=run_second)]
for thread in threads:
    thread.start()
assert snapshot.wait(20)
time.sleep(.3)
release.set()
for thread in threads:
    thread.join(30)
    assert not thread.is_alive()
assert results['A'] == 'committed' and results['B'] == 'SerializationFailure', results
with registry.cursor() as cr:
    e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
    g = e['erp.contract.guarantee'].browse(guarantee_id)
    assert g.action_create_return()['res_id'] == results['return_id']
    assert len(g.move_ids.filtered(lambda m: m.erp_guarantee_direction == 'return')) == 1
    try:
        with cr.savepoint():
            e['account.move'].browse(receipt_id).button_draft()
    except ValidationError:
        pass
    else:
        raise AssertionError('Cannot remove paid receipt backing a reserved return')
print('GUARANTEE_CONCURRENCY_PASSED', results)
