"""SECURITY FIX: propagate source OU restrictions to native accounting records."""
from odoo import api, models
from odoo.fields import Domain


class SourceMoveScope(models.Model):
    _inherit = 'account.move'

    @api.model
    def _erp_source_document_domain(self):
        # any! examines every source, including sources hidden from this user.
        invalid_unit = Domain('active', '=', False) | Domain(
            'assignment_ids', 'not any!', Domain('user_id', '=', self.env.uid))
        invalid_purchase = Domain('purchase_line_id', 'any!', Domain(
            'order_id', 'any!', Domain('erp_request_organization_id', 'any!', invalid_unit)))
        invalid_direct = Domain('erp_budget_organization_id', 'any!', invalid_unit)
        return Domain('line_ids', 'not any!', invalid_purchase | invalid_direct)

    @api.model
    def _erp_source_accounting_domain(self):
        valid = self._erp_source_document_domain()
        return valid & Domain('origin_payment_id', 'not any!',
                              Domain('invoice_ids', 'any!', ~valid))

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & self._erp_source_accounting_domain()


class SourceLineScope(models.Model):
    _inherit = 'account.move.line'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain(
            'move_id', 'any!', self.env['account.move']._erp_source_accounting_domain())


class SourcePaymentScope(models.Model):
    _inherit = 'account.payment'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain(
            'invoice_ids', 'not any!', ~self.env['account.move']._erp_source_accounting_domain())


class SourcePartialScope(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model
    def _access_domain(self, operation):
        valid = Domain('move_id', 'any!', self.env['account.move']._erp_source_accounting_domain())
        return super()._access_domain(operation) & Domain('debit_move_id', 'any!', valid) & Domain('credit_move_id', 'any!', valid)


class SourceFullScope(models.Model):
    _inherit = 'account.full.reconcile'

    @api.model
    def _access_domain(self, operation):
        return super()._access_domain(operation) & Domain('reconciled_line_ids', 'not any!',
            Domain('move_id', 'not any!', self.env['account.move']._erp_source_accounting_domain()))
