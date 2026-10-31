from odoo import http
from odoo.http import request
from odoo.addons.hr.controllers.hr_org_chart import HrOrgChartController


class ScopedHrOrgChartController(HrOrgChartController):
    def _visible_employees(self, ids, context):
        company_ids = context.get("allowed_company_ids", [request.env.company.id])
        return request.env["hr.employee.public"].with_context(
            allowed_company_ids=company_ids
        ).search([("id", "in", ids)])

    @http.route()
    def get_org_chart(self, employee_id, new_parent_id=None, new_job_title=None, **kw):
        result = super().get_org_chart(employee_id, new_parent_id, new_job_title, **kw)
        if "self" not in result:
            return result
        context = kw.get("context") or {}
        items = [result["self"], *result["managers"], *result["children"]]
        visible = self._visible_employees([item["id"] for item in items], context)
        visible_ids = set(visible.ids)
        result["managers"] = [item for item in result["managers"] if item["id"] in visible_ids]
        result["children"] = [item for item in result["children"] if item["id"] in visible_ids]
        # Core computes hierarchy counts with sudo. Return counts only for records
        # visible under the current user's organization and company permissions.
        public = visible.browse()
        for item in [result["self"], *result["managers"], *result["children"]]:
            item["direct_sub_count"] = public.search_count([("parent_id", "=", item["id"]), ("id", "!=", item["id"])])
            item["indirect_sub_count"] = public.search_count([("id", "child_of", item["id"]), ("id", "!=", item["id"])])
        # Do not disclose an otherwise invisible ancestor beyond the displayed list.
        result["managers_more"] = False
        return result

    @http.route()
    def get_subordinates(self, employee_id, subordinates_type=None, **kw):
        ids = super().get_subordinates(employee_id, subordinates_type, **kw)
        if not ids:
            return ids
        visible_ids = set(self._visible_employees(ids, kw.get("context") or {}).ids)
        return [employee_id for employee_id in ids if employee_id in visible_ids]
