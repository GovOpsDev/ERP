# Government request expense routing

Selected Thai government request purchase types route either to requisition or
native employee expense. The Finance action resolves the requester employee in
the request company, requires an expense-enabled product, copies original
currency and Budget provenance and returns the same live expense on retry.
PR Done remains Budget-eligible exactly as source approved/done semantics require.
Reset is blocked while a live linked expense exists. Existing private provenance
and native expense accounting rules remain authoritative.

Evidence: government-financial-61.log passed 179 cross-domain tests, including
native expense posting from a Done PR and PO bill/refund after PR Done.
