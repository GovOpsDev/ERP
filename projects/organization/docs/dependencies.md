# Dependencies

`erp_organization` depends on `erp_core` from the independent `shared/erp_core` repository; `erp_core` depends on Odoo 20 Community `base`. Mount both addon paths; no Enterprise or reverse domain dependency.

`erp_organization_hr` is an optional bridge depending on `erp_organization` and Odoo 20 Community `hr`. Installing `erp_organization` alone does not install HR. No reverse or Enterprise dependency.

`erp_organization_hr_employee` optionally depends on `erp_organization_hr` and therefore on `erp_organization`, `erp_core` and Community `hr`. No Enterprise dependency or reverse dependency.
