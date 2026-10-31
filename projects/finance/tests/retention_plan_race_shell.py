# Isolated test database only: creates committed synthetic accounting history.
import threading
import time
import unittest
from odoo import api
from odoo.addons.erp_finance.tests.test_retention import TestRetention
class Fixture(unittest.TestCase):
    make_request = TestRetention.make_request
    make_po = TestRetention.make_po
    make_bill = TestRetention.make_bill
    scenario = TestRetention.scenario
    retention_scenario = TestRetention.retention_scenario
    payment_wizard = TestRetention.payment_wizard
fixture = Fixture()
fixture.env = env
fixture.company = fixture.env['res.company'].create({'name': 'Procurement Company'})
fixture.unit = fixture.env['erp.organization.unit'].create({'name': 'Procurement Unit', 'code': 'PUR', 'company_id': fixture.company.id})
fixture.user = fixture.env['res.users'].create({'name': 'Procurement Approver', 'login': 'erp_pr_approver', 'company_id': fixture.company.id, 'company_ids': [(6, 0, [fixture.company.id])], 'group_ids': [(6, 0, [fixture.env.ref('erp_procurement.group_procurement_manager').id])]})
fixture.user.write({'group_ids': [(4, fixture.env.ref('account.group_account_invoice').id)]})
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
warehouse = env['stock.warehouse'].create({'name': 'Retention plan race warehouse', 'code': 'RPW', 'company_id': fixture.company.id})
fixture.test_env = fixture.test_env(context=dict(fixture.test_env.context, default_picking_type_id=warehouse.in_type_id.id))
bill = fixture.retention_scenario()
fixture.payment_wizard(bill, apply=True)._create_payments()
retention_id = bill.erp_retention_ids.id
request = fixture.make_request(10)
request.action_submit()
request.action_approve()
po = fixture.make_po(request, 10)
fixture.product.purchase_method = 'purchase'
po.button_confirm()
po.create_invoice_plan(2, '2026-06-01')
plan_id = po.erp_invoice_plan_ids.sorted('installment')[0].id
uid, company_id, registry = fixture.user.id, fixture.company.id, env.registry
env.cr.commit()

def race(model, identity, method):
    ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
    results = {}
    def first():
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                result = getattr(e[model].browse(identity), method)()
                results['document_id'] = result['res_id']
                ready.set()
                assert release.wait(20)
                cr.commit()
            results['A'] = 'committed'
        except Exception as exc:
            results['A'] = type(exc).__name__
            ready.set()
    def second():
        assert ready.wait(20)
        try:
            with registry.cursor() as cr:
                e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
                cr.execute('SELECT id FROM res_company WHERE id=%s', [company_id])
                cr.fetchone()
                snapshot.set()
                getattr(e[model].browse(identity), method)()
                cr.commit()
            results['B'] = 'committed'
        except Exception as exc:
            results['B'] = type(exc).__name__
            snapshot.set()
    threads = [threading.Thread(target=first), threading.Thread(target=second)]
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
        assert getattr(e[model].browse(identity), method)()['res_id'] == results['document_id']
    print('RETENTION_PLAN_RACE', model, results)
race('erp.finance.retention', retention_id, 'action_release')
race('erp.procurement.invoice.plan', plan_id, 'action_create_invoice')
print('RETENTION_PLAN_CONCURRENCY_PASSED')
