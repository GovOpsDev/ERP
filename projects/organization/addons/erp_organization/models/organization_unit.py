from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OrganizationUnit(models.Model):
    _name = "erp.organization.unit"
    _description = "Government Organization Unit"
    _order = "name, id"
    _check_company_auto = True

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        index=True, ondelete="restrict",
    )
    partner_id = fields.Many2one("res.partner", check_company=True, ondelete="restrict", string="Partner")
    parent_id = fields.Many2one(
        "erp.organization.unit", index=True, check_company=True, ondelete="restrict",
    )
    child_ids = fields.One2many("erp.organization.unit", "parent_id")
    assignment_ids = fields.One2many("erp.organization.assignment", "unit_id", string="User Assignments")

    _code_company_unique = models.Constraint(
        "UNIQUE (company_id, code)", "The unit code must be unique per company."
    )
    _name_company_unique = models.Constraint(
        "UNIQUE (company_id, name)", "The unit name must be unique per company."
    )

    @api.constrains("parent_id")
    def _check_parent_cycle(self):
        if self._has_cycle("parent_id"):
            raise ValidationError(_("An organization unit hierarchy cannot contain a cycle."))

    @api.model_create_multi
    def create(self, vals_list):
        values = []
        for vals in vals_list:
            vals = dict(vals)
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.context.get('default_company_id') or self.env.company.id)
            if 'partner_id' not in vals:
                vals['partner_id'] = self.env.context.get('default_partner_id') or company.partner_id.id
            if not vals['partner_id']:
                raise ValidationError(_("New organization units require a partner."))
            values.append(vals)
        return super().create(values)

    def write(self, vals):
        if 'partner_id' in vals and not vals['partner_id'] and self.filtered('partner_id'):
            raise ValidationError(_("An assigned organization partner cannot be cleared."))
        if "company_id" in vals and any(unit.company_id.id != vals["company_id"] for unit in self):
            raise ValidationError(_("The company of an organization unit cannot be changed."))
        return super().write(vals)


class OrganizationPartner(models.Model):
    _inherit = 'res.partner'

    def write(self, vals):
        if vals.get('company_id'):
            units = self.env['erp.organization.unit'].sudo().with_context(active_test=False).search([
                ('partner_id', 'in', self.ids), ('company_id', '!=', vals['company_id']),
            ], limit=1)
            if units:
                raise ValidationError(_('A partner used by another company organization cannot be moved to this company.'))
        return super().write(vals)
