"""Government PR types, methods, verification and committee provenance."""
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.erp_budget.models.budget_release import _review_internal

_government = ContextVar('erp_procurement_government', default=False)
_EVIDENCE = {'verified_by_id', 'date_verified', 'approved_by_id', 'date_approved'}


class ProcurementMethod(models.Model):
    _name = 'erp.procurement.method'
    _description = 'Government Procurement Method'
    _order = 'sequence, id'
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    active = fields.Boolean(default=True)

    def write(self, vals):
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise AccessError(_('Procurement methods cannot change company.'))
        return super().write(vals)


class ProcurementType(models.Model):
    _name = 'erp.procurement.type'
    _description = 'Government Procurement Category'
    _order = 'sequence, id'
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    product_id = fields.Many2one('product.product', check_company=True)
    active = fields.Boolean(default=True)

    def write(self, vals):
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise AccessError(_('Procurement categories cannot change company.'))
        return super().write(vals)


class PurchaseType(models.Model):
    _name = 'erp.procurement.purchase.type'
    _description = 'Government Purchase Type'
    _order = 'sequence, id'
    _check_company_auto = True
    name = fields.Char(required=True)
    code = fields.Char()
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    to_create = fields.Selection([('purchase_agreement', 'Purchase Agreement'), ('expense', 'Expense')], required=True)
    method_ids = fields.Many2many('erp.procurement.method', check_company=True)
    is_default = fields.Boolean()
    active = fields.Boolean(default=True)

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS erp_one_default_purchase_type ON erp_procurement_purchase_type(company_id) WHERE is_default AND active')
        return result

    def write(self, vals):
        if 'company_id' in vals and any(r.company_id.id != vals['company_id'] for r in self):
            raise AccessError(_('Purchase types cannot change company.'))
        if {'company_id', 'to_create', 'method_ids'} & vals.keys() and self.env['erp.procurement.request'].sudo().search_count([('purchase_type_id', 'in', self.ids), ('state', '!=', 'draft')]):
            raise UserError(_('Submitted requests retain their purchase type routing and allowed methods.'))
        return super().write(vals)


class GovernmentRequest(models.Model):
    _inherit = 'erp.procurement.request'
    procurement_type_id = fields.Many2one('erp.procurement.type', check_company=True, ondelete='restrict')
    purchase_type_id = fields.Many2one('erp.procurement.purchase.type', check_company=True, ondelete='restrict')
    procurement_method_id = fields.Many2one('erp.procurement.method', check_company=True, ondelete='restrict')
    conversion_route = fields.Selection(related='purchase_type_id.to_create')
    expense_reason = fields.Text()
    assigned_to = fields.Many2one('res.users', ondelete='restrict')
    verified_by_id = fields.Many2one('res.users', readonly=True, copy=False, ondelete='restrict')
    date_verified = fields.Date(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False, ondelete='restrict')
    date_approved = fields.Date(readonly=True, copy=False)
    committee_ids = fields.One2many('erp.procurement.committee', 'request_id', copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_EVIDENCE & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in _EVIDENCE):
            raise AccessError(_('Verification and approval evidence comes from workflow actions.'))
        for vals in vals_list:
            if 'purchase_type_id' not in vals:
                vals['purchase_type_id'] = self.env['erp.procurement.purchase.type'].search([('company_id', '=', vals.get('company_id', self.env.company.id)), ('is_default', '=', True)], limit=1).id
        return super().create(vals_list)

    def write(self, vals):
        if _EVIDENCE & vals.keys():
            if not _government.get() or vals.keys() - _EVIDENCE:
                raise AccessError(_('Verification and approval evidence cannot be forged.'))
            from .purchase_request import ProcurementRequest
            return super(ProcurementRequest, self).write(vals)
        return super().write(vals)

    @api.constrains('purchase_type_id', 'procurement_method_id', 'assigned_to', 'company_id')
    def _check_government_source(self):
        for request in self:
            if request.procurement_method_id and request.purchase_type_id and request.procurement_method_id not in request.purchase_type_id.method_ids:
                raise ValidationError(_('The procurement method must be allowed by the purchase type.'))
            if request.assigned_to and (not request.assigned_to.active or request.assigned_to.share or request.company_id not in request.assigned_to.company_ids):
                raise ValidationError(_('The purchase representative must be internal and belong to this company.'))

    @api.onchange('purchase_type_id')
    def _onchange_purchase_type(self):
        self.procurement_method_id = self.purchase_type_id.method_ids if len(self.purchase_type_id.method_ids) == 1 else False

    def _review_snapshot(self):
        values = super()._review_snapshot()
        values.update(purchase_type_id=self.purchase_type_id.id, procurement_type_id=self.procurement_type_id.id, procurement_method_id=self.procurement_method_id.id, conversion_route=self.conversion_route, expense_reason=self.expense_reason,
                      committees=[{'name': c.name, 'employee_id': c.employee_id.id, 'kind': c.kind, 'role': c.approve_role, 'note': c.note} for c in self.committee_ids])
        return values

    def action_submit(self):
        if any(r.purchase_type_id and (not r.purchase_type_id.active or not r.procurement_method_id or not r.procurement_method_id.active) for r in self):
            raise ValidationError(_('A configured government purchase type requires an active allowed method.'))
        self._check_government_source()
        return super().action_submit()

    def action_verify(self):
        self.ensure_one()
        self._manager_check()
        with self.env.cr.savepoint():
            self._lock_conversion()
            if self.state != 'to_approve':
                raise UserError(_('Only submitted requests can be verified.'))
            if self.verified_by_id:
                return True
            token, review_token = _government.set(True), _review_internal.set(True)
            try:
                self.write({'verified_by_id': self.env.uid, 'date_verified': fields.Date.context_today(self)})
                self._current_reviews().sudo().write({'verified_by_id': self.env.uid, 'date_verified': fields.Date.context_today(self)})
            finally:
                _review_internal.reset(review_token)
                _government.reset(token)
        return True

    def action_approve(self):
        if any(r.purchase_type_id and not r.verified_by_id for r in self):
            raise UserError(_('Verify the government request before final approval.'))
        with self.env.cr.savepoint():
            result = super().action_approve()
            token = _government.set(True)
            try:
                for request in self.filtered(lambda r: r.state == 'approved' and not r.approved_by_id):
                    request.write({'approved_by_id': self.env.uid, 'date_approved': fields.Date.context_today(self)})
            finally:
                _government.reset(token)
            return result

    def action_reset(self):
        with self.env.cr.savepoint():
            result = super().action_reset()
            token = _government.set(True)
            try:
                self.write(dict.fromkeys(_EVIDENCE, False))
            finally:
                _government.reset(token)
            return result

    def action_create_requisition(self):
        if any(r.purchase_type_id and r.conversion_route != 'purchase_agreement' for r in self):
            raise UserError(_('This purchase type routes to employee expense, not a requisition.'))
        return super().action_create_requisition()


class ProcurementCommittee(models.Model):
    _name = 'erp.procurement.committee'
    _description = 'Purchase Request Committee Member'
    _check_company_auto = True
    request_id = fields.Many2one('erp.procurement.request', required=True, check_company=True, ondelete='restrict')
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    organization_id = fields.Many2one(related='request_id.organization_id', store=True)
    employee_id = fields.Many2one('hr.employee', check_company=True, ondelete='restrict')
    name = fields.Char(required=True)
    kind = fields.Selection([('procurement', 'Procurement'), ('work_acceptance', 'Work Acceptance')], required=True)
    approve_role = fields.Selection([('chairman', 'Chairman'), ('committee', 'Committee')], required=True)
    note = fields.Text()
    _member_unique = models.Constraint('unique(request_id,employee_id)', 'An employee occurs only once on a request committee.')

    @api.onchange('employee_id')
    def _onchange_employee(self):
        if self.employee_id:
            self.name = self.employee_id.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            request = self.env['erp.procurement.request'].browse(vals.get('request_id', self.env.context.get('default_request_id')))
            request.check_access('write')
            request._lock_conversion()
            if request.state != 'draft':
                raise UserError(_('Committees can only change on draft requests.'))
            if vals.get('employee_id'):
                employee = self.env['hr.employee'].browse(vals['employee_id'])
                employee.check_access('read')
                vals.setdefault('name', employee.name)
        return super().create(vals_list)

    def write(self, vals):
        self.request_id.check_access('write')
        self.request_id._lock_conversion()
        if 'request_id' in vals or any(r.state != 'draft' for r in self.request_id):
            raise UserError(_('Submitted committee identities are immutable.'))
        if vals.get('employee_id'):
            self.env['hr.employee'].browse(vals['employee_id']).check_access('read')
        return super().write(vals)

    def unlink(self):
        self.request_id.check_access('write')
        self.request_id._lock_conversion()
        if any(r.state != 'draft' for r in self.request_id):
            raise UserError(_('Submitted committees cannot be removed.'))
        return super().unlink()


class GovernmentRequestLine(models.Model):
    _inherit = 'erp.procurement.request.line'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            request = self.env['erp.procurement.request'].browse(vals.get('request_id'))
            if not vals.get('product_id') and request.procurement_type_id.product_id:
                vals['product_id'] = request.procurement_type_id.product_id.id
        return super().create(vals_list)


class GovernmentRequisition(models.Model):
    _inherit = 'purchase.requisition'
    erp_po_type = fields.Selection([('agreement', 'Legal agreement required'), ('no_agreement', 'No legal agreement')], string='Government PO Type', copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if (any(v.get('erp_po_type') for v in vals_list) or self.env.context.get('default_erp_po_type')) and not self.env.su and not self.env.user.has_group('erp_procurement.group_procurement_manager'):
            raise AccessError(_('Procurement management is required to select the legal agreement route.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_po_type' in vals:
            self.check_access('write')
            if not self.env.su and not self.env.user.has_group('erp_procurement.group_procurement_manager'):
                raise AccessError(_('Procurement management is required to select the legal agreement route.'))
            if any(r.state != 'draft' or r.purchase_ids for r in self):
                raise UserError(_('Select the agreement requirement before confirming or creating RFQs.'))
        return super().write(vals)
