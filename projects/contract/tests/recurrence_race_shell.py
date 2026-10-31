# Isolated test DB only: commits synthetic records for a two-cursor race.
import threading
import time
import unittest
from odoo import api
from odoo.addons.erp_contract.tests.test_recurrence import TestContractRecurrence
class Fixture(unittest.TestCase):
    make_contract = TestContractRecurrence.make_contract
    recurring = TestContractRecurrence.recurring
    generate = TestContractRecurrence.generate
fixture = Fixture()
fixture.env = env
fixture.company = fixture.env['res.company'].create({'name': 'Contract budget company'})
fixture.unit = fixture.env['erp.organization.unit'].create({'name': 'Contract budget OU', 'code': 'CB', 'company_id': fixture.company.id})
fixture.user = fixture.env['res.users'].create({'name': 'Contract budget reviewer', 'login': 'contract_budget_reviewer', 'company_id': fixture.company.id, 'company_ids': [(6, 0, [fixture.company.id])], 'group_ids': [(6, 0, [fixture.env.ref('erp_contract.group_contract_manager').id, fixture.env.ref('account.group_account_invoice').id])]})
fixture.env['erp.organization.assignment'].create({'user_id': fixture.user.id, 'unit_id': fixture.unit.id})
group = fixture.env['erp.budget.fund.group'].create({'name': 'Contract fund group', 'company_id': fixture.company.id})
fixture.fund = fixture.env['erp.budget.fund'].create({'name': 'Contract fund', 'group_id': group.id, 'company_id': fixture.company.id})
fixture.period = fixture.env['erp.budget.period'].create({'name': 'Contract period', 'company_id': fixture.company.id, 'date_from': '2026-01-01', 'date_to': '2026-12-31'})
plan = fixture.env['account.analytic.plan'].create({'name': 'Contract analytics'})
fixture.analytic = fixture.env['account.analytic.account'].create({'name': 'Contract analytic', 'plan_id': plan.id, 'company_id': fixture.company.id})
fixture.account = fixture.env['account.account'].create({'name': 'Contract expense', 'code': 'CNT001', 'account_type': 'expense', 'company_ids': [(6, 0, [fixture.company.id])]})
payable = fixture.env['account.account'].create({'name': 'Contract payable', 'code': 'CNTPAY', 'account_type': 'liability_payable', 'reconcile': True, 'company_ids': [(6, 0, [fixture.company.id])]})
fixture.product = fixture.env['product.product'].create({'name': 'Contract service', 'type': 'service', 'purchase_ok': True})
fixture.product.with_company(fixture.company).product_tmpl_id.property_account_expense_id = fixture.account
fixture.vendor = fixture.env['res.partner'].create({'name': 'Contract supplier', 'supplier_rank': 1})
fixture.vendor.with_company(fixture.company).property_account_payable_id = payable
fixture.journal = fixture.env['account.journal'].create({'name': 'Contract purchases', 'code': 'CTST', 'type': 'purchase', 'company_id': fixture.company.id})
vals = {'company_id': fixture.company.id, 'period_id': fixture.period.id, 'organization_id': fixture.unit.id, 'analytic_id': fixture.analytic.id, 'amount': 120}
fixture.ac = fixture.env['erp.budget.control'].create(dict(vals, name='Contract analytic limit', level='analytic'))
fixture.fc = fixture.env['erp.budget.control'].create(dict(vals, name='Contract fund limit', level='fund', fund_id=fixture.fund.id))
(fixture.ac | fixture.fc).action_open()
fixture.e = fixture.env(user=fixture.user, context={'allowed_company_ids': [fixture.company.id]})

contract, line = fixture.recurring()
bill = fixture.generate(contract)
cycle = bill.erp_contract_cycle_id
bill.button_cancel()
uid, company_id, cycle_id, contract_id = fixture.user.id, fixture.company.id, cycle.id, contract.id
registry = env.registry
env.cr.commit()
ready, snapshot, release = threading.Event(), threading.Event(), threading.Event()
results = {}
def worker_a():
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            results['bill_id'] = e['erp.contract.cycle'].browse(cycle_id).action_create_invoice()['res_id']
            ready.set()
            assert release.wait(20)
            cr.commit()
        results['A'] = 'committed'
    except Exception as exc:
        results['A'] = type(exc).__name__
        ready.set()
def worker_b():
    assert ready.wait(20)
    try:
        with registry.cursor() as cr:
            e = api.Environment(cr, uid, {'allowed_company_ids': [company_id]})
            cr.execute('SELECT id FROM erp_contract_contract WHERE id=%s', [contract_id])
            cr.fetchone()
            snapshot.set()
            e['erp.contract.cycle'].browse(cycle_id).action_create_invoice()
            cr.commit()
        results['B'] = 'committed'
    except Exception as exc:
        results['B'] = type(exc).__name__
        snapshot.set()
threads = [threading.Thread(target=worker_a), threading.Thread(target=worker_b)]
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
    current = e['erp.contract.cycle'].browse(cycle_id)
    assert current.action_create_invoice()['res_id'] == results['bill_id']
    live = current.invoice_ids.filtered(lambda m: m.state != 'cancel')
    assert len(live) == 1 and len(current.invoice_ids) == 2
    live.action_post()
    actuals = e['erp.budget.move'].sudo().search([('control_id', '=', fixture.ac.id), ('move_type', '=', 'actual')])
    assert sum(actuals.mapped('amount')) == 10
    assert not e['erp.budget.move'].sudo().search_count([('control_id', '=', fixture.ac.id), ('move_type', '=', 'contract_commitment')])
    cr.commit()
print('CONTRACT_CYCLE_CONCURRENCY_PASSED', results)
