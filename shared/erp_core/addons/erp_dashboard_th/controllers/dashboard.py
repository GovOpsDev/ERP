from odoo.http import request, route
from odoo.addons.spreadsheet_dashboard.controllers.dashboards_controllers import DashboardDataRoute


class CompanyDashboardDataRoute(DashboardDataRoute):
    @route()
    def get_dashboard_data(self, dashboard):
        # Unlike ORM calls, the native dashboard HTTP loader sends no user
        # context. Match web/core/user.js: the first cids entry is current.
        # This also makes the empty/sample check use the selected companies.
        raw = request.httprequest.cookies.get('cids', '')
        if raw:
            try:
                company_ids = [int(value) for value in raw.split('-')]
            except ValueError:
                raise request.not_found()
            dashboard = dashboard.with_context(allowed_company_ids=company_ids)
            dashboard.env.companies  # validate ALL ids; never elevate privileges
        return super().get_dashboard_data(dashboard)
