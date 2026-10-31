import math

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal


class ProcurementTier(models.Model):
    _name = 'erp.procurement.tier'
    _description = 'Purchase Request Approval Tier'
    _order = 'sequence, id'

    kind = fields.Selection([('request', 'Purchase Request'), ('purchase', 'Purchase Order')], required=True, default='request')
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    sequence = fields.Integer(required=True, default=10)
    minimum_amount = fields.Monetary(required=True, default=0)
    reviewer_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    active = fields.Boolean(default=True)
    _sequence_company_unique = models.Constraint('UNIQUE(company_id, kind, sequence)', 'Approval tier sequence must be unique per company and document type.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('company_id', self.env.company.id) not in self.env.companies.ids:
                raise AccessError(_('Tier company must be active.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and 'company_id' in vals and vals['company_id'] not in self.env.companies.ids:
            raise AccessError(_('Tier company must be active.'))
        return super().write(vals)

    @api.constrains('company_id', 'minimum_amount', 'reviewer_id')
    def _check_tier(self):
        for tier in self:
            if not math.isfinite(tier.minimum_amount) or tier.minimum_amount < 0 or tier.company_id not in tier.reviewer_id.company_ids or tier.reviewer_id.share:
                raise ValidationError(_('The reviewer must be internal and allowed in the tier company; the threshold must be nonnegative.'))


class ProcurementReview(models.Model):
    _name = 'erp.procurement.review'
    _description = 'Purchase Request Approval Review'
    _order = 'sequence, id'

    request_id = fields.Many2one('erp.procurement.request', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True, index=True)
    organization_id = fields.Many2one(related='request_id.organization_id', store=True, index=True)
    reviewer_id = fields.Many2one('res.users', required=True, ondelete='restrict')
    sequence = fields.Integer(required=True)
    round_number = fields.Integer(required=True, default=1)
    request_snapshot = fields.Json(readonly=True)
    decided_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    decided_at = fields.Datetime(readonly=True)
    verified_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    date_verified = fields.Date(readonly=True)
    state = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], required=True, default='pending')
    _request_sequence_unique = models.Constraint('UNIQUE(request_id, round_number, sequence)', 'Review sequence must be unique per request submission.')

    @api.model_create_multi
    def create(self, vals_list):
        if not _review_internal.get():
            raise AccessError(_('Reviews are created by submission.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _review_internal.get() or vals.keys() - {'state', 'verified_by_id', 'date_verified'}:
            raise AccessError(_('Review evidence is recorded by workflow actions.'))
        if vals.get('state') in ('approved', 'rejected'):
            vals = dict(vals, decided_by_id=self.env.uid, decided_at=fields.Datetime.now())
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Approval reviews are retained for audit.'))
