from types import SimpleNamespace


def source_activity_allocation(case, manager, company, unit, analytic, fund, account, prefix, control_level="legacy"):
    """A reviewed source allocation whose activities share one budget account."""
    env = case.env(user=manager, context={'allowed_company_ids': company.ids})
    kpis = env['erp.budget.kpi'].create([{'name': prefix + name, 'company_id': company.id} for name in (' KPI A', ' KPI B')])
    activities = env['erp.budget.activity'].create([{'name': prefix + name, 'company_id': company.id, 'account_id': account.id, 'kpi_id': kpi.id} for name, kpi in zip((' Activity A', ' Activity B'), kpis)])
    template = env['erp.budget.template'].create({'name': prefix + ' template', 'company_id': company.id, 'activity_line_ids': [(0, 0, {'activity_id': activity.id, 'kpi_id': kpi.id}) for activity, kpi in zip(activities, kpis)]})
    period = case.env['erp.budget.period'].create({'name': prefix + ' period', 'company_id': company.id, 'date_from': '2027-01-01', 'date_to': '2027-12-31', 'release_policy': 'formal', 'template_id': template.id, 'control_level': control_level})
    allocation = env['erp.budget.allocation'].create({'name': prefix + ' allocation', 'company_id': company.id, 'period_id': period.id, 'line_ids': [(0, 0, {'organization_id': unit.id, 'analytic_id': analytic.id, 'fund_id': fund.id, 'allocated_amount': 100})]})
    allocation.action_done()
    allocation.plan_id.action_confirm()
    fund_control = allocation.line_ids.control_id
    fund_control.action_open()
    base = {'company_id': company.id, 'period_id': period.id, 'organization_id': unit.id, 'analytic_id': analytic.id, 'level': 'analytic'}
    controls = env['erp.budget.control'].create([dict(base, name=prefix+' total', amount=100)] if control_level == 'analytic' else [dict(base, name=prefix+' A', kpi_id=kpis[0].id, amount=40), dict(base, name=prefix+' B', kpi_id=kpis[1].id, amount=60)])
    reviewer = case.env['res.users'].create({'name': prefix + ' reviewer', 'login': prefix.lower().replace(' ', '_') + '_reviewer', 'company_id': company.id, 'company_ids': [(6, 0, company.ids)], 'group_ids': [(6, 0, case.env.ref('erp_budget.group_budget_manager').ids)]})
    case.env['erp.organization.assignment'].create({'user_id': reviewer.id, 'unit_id': unit.id})
    case.env['erp.budget.kpi.tier'].create({'company_id': company.id, 'organization_id': unit.id, 'sequence': 10, 'reviewer_id': reviewer.id})
    release = env['erp.budget.kpi.release'].create({'name': prefix + ' planning', 'plan_line_id': allocation.plan_id.line_ids.id, 'released_amount': 100, 'line_ids': [(0, 0, {'control_id': control.id, **({'planning_ids': [(0, 0, {'date_from': period.date_from, 'date_to': period.date_to, 'amount': amount, 'kpi_id': kpi.id}) for amount, kpi in zip((40, 60), kpis)]} if control_level == 'analytic' else {})}) for control in controls]})
    release.action_submit()
    release.with_user(reviewer).action_approve()
    return SimpleNamespace(env=env, allocation=allocation, activities=activities, controls=controls, fund_control=fund_control, period=period, template=template, reviewer=reviewer)
