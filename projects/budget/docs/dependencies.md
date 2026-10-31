# Dependencies

`erp_budget` depends on `erp_organization`, which in turn depends on `erp_core`. No Enterprise modules are used. The current master data is company-wide; downstream transactional data needs explicit Organization Contract v1 scope and its own record rules.

The source `budget_allocation` depends on `budget_plan` and `analytic_tag_dimension_enhanced`; `budget_plan` depends on `budget_control`; `budget_control` depends on accounting, date ranges and a web matrix widget. The operating-unit extension derives unit context from analytic accounts. Accounting, analytic, OU integration, and the legacy widget have not yet been migrated or evaluated end-to-end.
