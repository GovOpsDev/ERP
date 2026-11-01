from odoo.http import request, route
from odoo.addons.spreadsheet_dashboard.controllers.dashboards_controllers import DashboardDataRoute


class BudgetDashboardDataRoute(DashboardDataRoute):
    @route()
    def get_dashboard_data(self, dashboard):
        if dashboard == request.env.ref('erp_budget_dashboard.dashboard_project_budget', raise_if_not_found=False):
            # The native HTTP loader does not send the ORM context. Read the same
            # cids cookie as web/core/user.js, then let env.companies validate it.
            raw = request.httprequest.cookies.get('cids', '')
            if raw:
                try:
                    ids = [int(value) for value in raw.split('-')]
                except ValueError:
                    raise request.not_found()
                dashboard = dashboard.with_context(allowed_company_ids=ids)
                dashboard.env.companies  # rejects unauthorized company IDs
        return super().get_dashboard_data(dashboard)
