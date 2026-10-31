# ERP Core

Shared lightweight foundation for Thai Government ERP on Odoo 20 Community. Upstream reference: [NSTDA ERP-Government](https://github.com/NSTDA/ERP-Government). Contains `erp_core`, depending only on Odoo `base`. No domain models or business logic are implemented.

Migration status: PARTIAL foundation scaffold. Mapping: the previous `erp_base` scaffold was renamed; no upstream implementation was copied. Test status: clean install and upgrade passed; see `../../projects/organization/docs/test-report.md`. Gaps: evidence-driven shared abstractions remain to be discovered. Next: support Organization requirements only when shared behavior is established.
