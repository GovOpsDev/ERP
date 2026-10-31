# Purchase invoice plans

Source OCA purchase-workflow `7eed5d2dd34d14edd74c6c80c235d0c75619f1d8` defines
installment date/percentage, quantity scaling and a final remainder, with native
invoice links and no additional Budget capacity. `erp.procurement.invoice.plan`
implements these semantics using Odoo 20 native PO invoice values and Product Unit
precision. Received-quantity billing policy is honored before creating an installment.

Redesign: source ownership, company/OU, sequential creation, used-plan immutability,
retained cancellation history, native credit support and row-version locking enforce
server invariants. Repeating a creation action returns its live invoice; a cancelled
invoice permits a replacement and retains the original link. Final calculations use
prior native invoice quantities, including refunds. Computed amounts do not depend
on the order Odoo computes sibling records.

Finance supplies the selected source retention and deposit extensions; see
`../../finance/docs/source-retention-plans.md`. Contract reuses installment safety
with its own source identity and native contract bill lines. The canonical Budget
service continues to own all commitments and actuals.

Evidence: `plans-retention-45.log` (10 tests, 0 failures/errors) and
`retention-plan-race-01.log` (two real transactions, one commit, one serialization
retry, one invoice after fresh retry), under the durable closure evidence directory.
The final affected-domain regression is recorded in Finance's test report.

Procurement still requires government request lifecycle/metadata, request currency
and configured PO tier parity. These plans do not close those independent rows.
