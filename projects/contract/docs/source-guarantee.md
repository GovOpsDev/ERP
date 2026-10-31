# Purchase guarantee accounting — migrated

Exact source: `l10n_th_gov_purchase_guarantee` and its Budget allocation bridge at
NSTDA l10n-thailand `5ebe30a8be97`. Source guarantee methods select an account and
RFQ/PO/requisition stage; instrument types select native accounting or document
custody. Customer invoices receive guarantees, vendor bills return them, and paid
amounts come from native reconciliation. The return date is the payment date.

`erp.contract.guarantee` preserves those behaviors with company/assigned-OU scope,
source fund/analytics, and native invoices/bills/payments. Non-cash instruments
retain document references and manual return dates. Financial documents never
create another PR/PO/Contract commitment or Budget actual. Method/type presets and
real company accounts are production configuration.

Security redesign: stable immutable financial links; native post/reset/cancel
boundaries; receipt claims cannot exceed face value; even draft return claims
cannot exceed paid receipts. Reset removes native reconciliation atomically and
cannot orphan an existing return. Paid partial values/endpoints cannot be rewritten
or over-reconciled. OU revocation hides related payment/GL/reconcile records.
Row locks plus a write version serialize concurrent return requests; retry returns
the same draft instead of another liability. Financial history is never deleted.

Runtime evidence under `../../../../test-evidence/closure-20261031/`:
- `guarantee-financial-regression-32.log`: 126 Contract/Finance/Asset tests,
  zero failures/errors (before explicit payment-reset case).
- `retention-guarantee-36.log`: 10 tests, zero failures/errors, including all seven
  guarantee cases and three retention dependency cases.
- `guarantee-race-03.log`: real independent transactions; one committed, one
  SerializationFailure; fresh retry returns the existing bill; receipt reset
  while a return is reserved fails. DB `closure_20261031_guarantee_race_01` retained.

Contract remains PARTIAL for the other exact legal/recurrence/invoice-plan rows.
