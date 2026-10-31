# Asset lifecycle v1 — DRAFT / PARTIAL

Historical initial implementation note. Current source parity and reversal semantics
are defined in [source-mapping.md](source-mapping.md).

VERIFIED UPSTREAM: profile-eligible non-tax posted accounting lines create assets; OCA supports aggregate and product-item modes. The Thai government extension uses the linked acceptance date. Asset creation is not triggered by acceptance alone.

REDESIGNED / VERIFIED ODOO 20: accepted PO and linked vendor bill create immutable acquisition snapshots with company/OU, source, quantity, accounting balance and acceptance date. Aggregate 4+6 partial bills, goods and service paths, unprofiled bills, idempotency and access boundaries were exercised. Item mode produces one numbered acquisition per whole unit and preserves total rounded value. Managers explicitly link to an OCA depreciation asset; no historical backfill occurs.

OCA-BASED / VERIFIED TESTED SUBSET: activation, board generation and a balanced posted depreciation move; duplicate posting is rejected. A disposal wizard generates a draft accounting move which the test explicitly posts; the asset is removed and acquisition remains. Standalone OCA tests cover additional calculations. These results do not establish complete Thai depreciation, low-value, sale or loss behavior.

OCA-BASED / REDESIGNED: a same-company, same-OU AUC transfer posts a reclassification journal, removes source assets and creates scoped destination assets with immutable group-level history. Split and merge are tested; already-depreciated, cross-company and cross-OU transfers are rejected. Thai transfer sub-status is not yet implemented. See `transfer-architecture.md`.

GUARDED / UNSUPPORTED: OU/location/custodian transfer history and asset-backed credit notes/reset remain unsupported. Refund/reset are rejected; a native stock return does not reconcile the asset or its accounting. See `oca-asset-port.md` and `test-report.md`.

Browser, production migration, filestore, load and concurrency scale are NOT TESTED. This contract is not frozen.
