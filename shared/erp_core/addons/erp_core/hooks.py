"""Initialize only Odoo's pristine placeholder company on first installation."""
import logging

_logger = logging.getLogger(__name__)
# Guard all installed business domains; a configured database is never relabelled.
BUSINESS_MODELS = (
    'account.move', 'account.move.line', 'purchase.order', 'sale.order',
    'stock.move', 'stock.quant', 'hr.expense', 'account.asset',
    'erp.budget.control', 'erp.budget.plan', 'erp.procurement.request',
    'erp.contract.contract', 'erp.contract.agreement', 'erp.asset.asset',
)


def post_init_hook(env):
    companies = env['res.company'].with_context(active_test=False).search([])
    company = env.ref('base.main_company')
    # A first-install bootstrap is intentionally narrower than a migration. In
    # particular, no existing UAT or named organization is changed on installation.
    if len(companies) != 1 or company.name != 'My Company':
        return
    if company.currency_id != env.ref('base.USD'):
        return
    # Odoo seeds the placeholder in the US. Account chart installation follows
    # the country and would otherwise restore USD later in a one-pass install.
    # Do not touch a company with an explicitly configured country or chart.
    if company.country_id and company.country_id.code not in {'US', 'TH'}:
        return
    if 'chart_template' in company._fields and company.chart_template:
        return
    for model in BUSINESS_MODELS:
        if model in env.registry and env[model].with_context(active_test=False).search_count([], limit=1):
            _logger.info('THB bootstrap skipped: existing records in %s', model)
            return
    company.write({'country_id': env.ref('base.th').id, 'currency_id': env.ref('base.THB').id})
    _logger.info('Pristine main company initialized for Thailand/THB; existing currencies are not migrated')
