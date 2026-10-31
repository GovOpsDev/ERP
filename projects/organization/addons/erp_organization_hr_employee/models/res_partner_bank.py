from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    erp_security_employee_ids = fields.One2many(
        "hr.employee", "work_contact_id", bypass_search_access=True,
        groups="base.group_no_one", context={"active_test": False},
    )


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    erp_security_employee_ids = fields.Many2many(
        "hr.employee", relation="employee_bank_account_rel",
        column1="bank_account_id", column2="employee_id", bypass_search_access=True,
        groups="base.group_no_one", context={"active_test": False},
    )
