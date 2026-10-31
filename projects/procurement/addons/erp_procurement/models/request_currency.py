"""PR estimates and thresholds use a frozen company-currency conversion."""
from contextvars import ContextVar
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_rate_transfer = ContextVar('erp_pr_rate_transfer', default=False)
_capture = ContextVar('erp_pr_currency_capture', default=False)
_PROTECTED = {'erp_budget_fx_rate', 'erp_budget_rate_captured'}


class RequestCurrency(models.Model):
    _inherit = 'erp.procurement.request'
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id, ondelete='restrict')
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    erp_budget_manual_rate = fields.Float(string='Company Currency per Document Unit', digits=0, help='Zero uses the native rate on the request date. Positive values require Budget/accounting management.')
    erp_budget_fx_rate = fields.Float(readonly=True, copy=False, digits=0)
    erp_budget_rate_captured = fields.Boolean(readonly=True, copy=False)
    total_company_currency = fields.Monetary(compute='_compute_company_estimate', currency_field='company_currency_id')

    def _auto_init(self):
        self.env.cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name='erp_procurement_request' AND column_name='currency_id'")
        new_currency = not self.env.cr.fetchone()
        result = super()._auto_init()
        if new_currency:
            self.env.cr.execute('UPDATE erp_procurement_request r SET currency_id=c.currency_id FROM res_company c WHERE r.company_id=c.id')
        return result

    def action_create_requisition(self):
        token = _rate_transfer.set(True)
        try:
            return super().action_create_requisition()
        finally:
            _rate_transfer.reset(token)

    @api.depends('line_ids.estimated_cost', 'currency_id', 'erp_budget_manual_rate', 'erp_budget_fx_rate', 'erp_budget_rate_captured', 'date_start', 'state')
    def _compute_company_estimate(self):
        for request in self:
            request.total_company_currency = sum(line._budget_estimated_cost() for line in request.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if any(_PROTECTED & v.keys() for v in vals_list) or any('default_' + n in self.env.context for n in _PROTECTED):
            raise AccessError(_('The request workflow captures exchange rates.'))
        for vals in vals_list:
            company = self.env['res.company'].browse(vals.get('company_id', self.env.company.id))
            vals.setdefault('currency_id', company.currency_id.id)
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals.get('erp_budget_manual_rate', self.env.context.get('default_erp_budget_manual_rate', 0)) or 0)
        return super().create(vals_list)

    def write(self, vals):
        if _PROTECTED & vals.keys():
            if not _capture.get() or vals.keys() - _PROTECTED:
                raise AccessError(_('Captured request rates are immutable.'))
            from .purchase_request import ProcurementRequest
            return super(ProcurementRequest, self).write(vals)
        if 'erp_budget_manual_rate' in vals:
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals['erp_budget_manual_rate'] or 0)
        return super().write(vals)

    @api.constrains('currency_id', 'company_id', 'erp_budget_manual_rate')
    def _check_request_currency(self):
        for request in self:
            if request.currency_id == request.company_currency_id and request.erp_budget_manual_rate not in (0, 1):
                raise ValidationError(_('The same-currency conversion rate must be one.'))

    def _request_company_rate(self):
        self.ensure_one()
        if self.state != 'draft':
            # Old target requests were company-currency documents; preserve that history.
            return self.erp_budget_fx_rate if self.erp_budget_rate_captured else 1
        return self.env['erp.budget.control.service']._amount_rate(self.currency_id, self.company_id, self.date_start, self.erp_budget_manual_rate)

    def action_submit(self):
        with self.env.cr.savepoint():
            self._lock_conversion()
            token = _capture.set(True)
            try:
                for request in self:
                    request.write({'erp_budget_fx_rate': request._request_company_rate(), 'erp_budget_rate_captured': True})
            finally:
                _capture.reset(token)
            return super().action_submit()

    def action_refresh_currency(self):
        if any(request.state != 'draft' for request in self):
            raise UserError(_('Only draft request rates can be refreshed.'))
        for request in self:
            rate = self.env['erp.budget.control.service']._amount_rate(request.currency_id, request.company_id, request.date_start)
            request.write({'erp_budget_manual_rate': rate})
        return True


class RequestLineCurrency(models.Model):
    _inherit = 'erp.procurement.request.line'
    currency_id = fields.Many2one(related='request_id.currency_id')
    company_currency_id = fields.Many2one(related='company_id.currency_id')
    estimated_cost_company_currency = fields.Monetary(compute='_compute_company_estimate', currency_field='company_currency_id')

    def _budget_estimated_cost(self):
        self.ensure_one()
        return self.company_currency_id.round(self.estimated_cost * self.request_id._request_company_rate())

    @api.depends('estimated_cost', 'request_id.currency_id', 'request_id.erp_budget_manual_rate', 'request_id.erp_budget_fx_rate', 'request_id.erp_budget_rate_captured', 'request_id.date_start', 'request_id.state')
    def _compute_company_estimate(self):
        for line in self:
            line.estimated_cost_company_currency = line._budget_estimated_cost()

    def _budget_amount_snapshot(self):
        return {'scope': 'request', 'currency_id': self.currency_id.id, 'company_currency_id': self.company_currency_id.id, 'company_rate': self.request_id._request_company_rate(), 'document_amount': self.estimated_cost, 'company_amount': self._budget_estimated_cost()}


class RequestAmountSnapshot(models.Model):
    _inherit = 'erp.budget.move'

    def _source_amount_snapshot(self, values):
        model, sep, identifier = (values.get('source_key') or '').partition(':')
        if sep and model == 'erp.procurement.request.line' and identifier.isdigit():
            line = self.env[model].browse(int(identifier)).exists()
            if line:
                return line._budget_amount_snapshot()
        return super()._source_amount_snapshot(values)


class RequisitionCurrency(models.Model):
    _inherit = 'purchase.requisition'
    erp_budget_manual_rate = fields.Float(string='Budget Manual Exchange Rate', digits=0)

    @api.depends('vendor_id', 'company_id', 'line_ids.erp_request_line_id.request_id.currency_id')
    def _compute_currency_id(self):
        super()._compute_currency_id()
        for requisition in self:
            currencies = requisition.line_ids.erp_request_line_id.currency_id
            if len(currencies) == 1:
                requisition.currency_id = currencies

    @api.constrains('currency_id', 'line_ids')
    def _check_source_currency(self):
        for requisition in self:
            currencies = requisition.line_ids.erp_request_line_id.currency_id
            if currencies and (len(currencies) != 1 or currencies != requisition.currency_id):
                raise ValidationError(_('A sourced requisition must preserve its request price currency.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not _rate_transfer.get():
                self.env['erp.budget.control.service']._check_manual_amount_rate(vals.get('erp_budget_manual_rate', self.env.context.get('default_erp_budget_manual_rate', 0)) or 0)
        return super().create(vals_list)

    def write(self, vals):
        if 'erp_budget_manual_rate' in vals:
            if any(r.state != 'draft' for r in self):
                raise UserError(_('Only draft requisitions may change their budget rate.'))
            self.env['erp.budget.control.service']._check_manual_amount_rate(vals['erp_budget_manual_rate'] or 0)
        return super().write(vals)

    def action_create_rfq(self):
        token = _rate_transfer.set(True)
        try:
            return super().action_create_rfq()
        finally:
            _rate_transfer.reset(token)
