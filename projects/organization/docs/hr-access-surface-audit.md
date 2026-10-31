# HR operating-unit access surface audit — PARTIAL

Inspected local Odoo Community 20.0 source `a240a91eb01223f59190f4853f748d675f68eaf2` under `/home/patrixr/GovOpsDev/odoo_build/odoo`, and tested image `odoo:20.0` ID `sha256:61e3c71b0503c5f658e604c3e340bede20b97d05f726179fa006eae50a32fd23` (runtime reported `20.0-20261015`). The local source and image were not proven bit-identical. Audit is scoped to Community HR and selected core surfaces, not every installed addon or all external APIs. Risk reflects residual risk after this change; no claim of complete HR confidentiality.

| Surface | Model/Route | Access path | Uses sudo | Existing protection | OU scoped? | Risk | Action |
|---|---|---|---|---|---|---|---|
| Employee ORM | `hr.employee` | search, search_read, browse/read, name_search, export | Core has internal sudo/fallback | Project `ir.access`; native HR/company rights | Yes, selected paths tested | MEDIUM | TEST ONLY |
| Public profile | `hr.employee.public` | search, name_search, direct read, avatar and hierarchy fields | Core related fields and counts use sudo | Project employee/public company rules; scoped child counts | Yes, selected fields tested | MEDIUM | HARDEN |
| Versions | `hr.version` | search/read and employee target writes | Core `_inherits` and some computations | Project version rule, target check, native company rule | Yes, linked versions tested; unlinked retain native rights | MEDIUM | TEST ONLY |
| Hierarchy HTTP | `/hr/get_org_chart`, `/hr/get_subordinates` | JSON-RPC direct IDs, manager chain and descendants | Core traverses ancestors with sudo and computes counts via sudo | Project controller filters returned IDs, recomputes visible counts | Yes for tested routes | MEDIUM | HARDEN |
| Related HR models | `hr.employee.location`, `hr.employee.departure` | search/read and employee target write | Related fields may use elevated computation | Project model-specific `ir.access` and target checks | Yes, selected CRUD paths | MEDIUM | HARDEN |
| Employee resource | `resource.resource` | direct read/search of employee name | Security helper relation bypasses comodel search rules only | Project global restriction only excludes resources with inaccessible linked employees; native resource/company rules | Yes, selected paths and unrelated resources tested | HIGH | HARDEN |
| Work contact / bank | `res.partner`, `res.partner.bank` | work contact name, employee-linked bank account | Core bank `_search_employee_id` uses sudo | Project restrictions apply only where linked to employee or its work contact; unlinked contacts/banks unchanged in tests | Yes for tested links | HIGH | HARDEN |
| Attachments | `ir.attachment`, `/web/content`, `/web/image` | `res_model`/`res_id`, direct ID and avatar downloads | Core checks referenced record; tokens/public may intentionally bypass | Native `res_access_read` and project referenced-model rules | Yes for non-public, no-token examples | HIGH | TEST ONLY |
| Chatter | `mail.message` | message search and direct read on employee | Core mail has privileged paths | Native message access to linked record; project employee rule | Yes for tested employee messages | HIGH | TEST ONLY |
| Followers / activity | `mail.followers`, `mail.activity`, mail routes | relational, notification, direct ID | Various | Native mail access; project employee rule does not cover every related route | Not established | HIGH | DOCUMENT LIMITATION |
| Export | `/web/export/csv`, `/web/export/xlsx`, `export_data` | explicit IDs or mixed IDs | Standard request env | Native export group and employee access rules | Yes at ORM export layer | MEDIUM | TEST ONLY |
| Reports | `hr.hr_employee_print_badge`, `/report/html/...` | QWeb employee docs from requested IDs | report metadata sudo, rendering in request environment | Employee record read checks | Yes for badge HTML and mixed IDs | HIGH | TEST ONLY |
| Other related data | `res.users`, other `res.partner` relations, resource calendars, other apps | identity, mail, salary and indirect employee references | Some core computations use sudo | Native model-specific access; not all links mapped | Not established | BLOCKER | DOCUMENT LIMITATION |
| Browser | employee directory and widgets | live browser login, company switch | UI dependent | Relies on routes/models | Not established | MEDIUM | DOCUMENT LIMITATION |

## Controller findings

`addons/hr/controllers/hr_org_chart.py` declares authenticated JSON-RPC `/hr/get_org_chart`, `/hr/get_subordinates`, and `/hr/get_redirect_model`. `_get_employee` checks `hr.employee.public`, but `get_org_chart` uses a sudo parent before checking that parent: a regression test observed the hidden manager's ID/name in its output. `get_subordinates` uses a related field computed with sudo, and core public/private hierarchy counts also included hidden staff. The project controller rechecks returned IDs, filters hierarchy/subordinates and recomputes visible counts; `managers_more` is intentionally false to avoid disclosing a hidden ancestor, so that UI indicator is conservative. Authenticated HTTP tests verify the routes and an unauthorized requested employee. The HR webclient store handler uses `search_fetch` under the request environment; its avatar store and unrelated mail endpoints have not been exhaustively HTTP-tested.

`addons/web/controllers/binary.py` exposes public `/web/content` and `/web/image`; it delegates to `ir.binary` and attachment checks and can use access tokens or public attachments. HTTP tests cover private/no-token attachment IDs, download after assignment revocation, and public-employee avatar downloads. Explicit public flags, bearer/access-token sharing, cached URLs and other controllers were not tested and may intentionally grant access independent of OU. Do not publish sensitive attachments or issue tokens without separate policy and review.

## Confirmed fixes and trade-offs

1. Org-chart hidden-manager leak and sudo-derived hierarchy counts/IDs: controller and public/private computed fields now use visible records. Tests cover representative paths, changing active companies with the same primary company, and assignment revocation without restart; other hierarchy methods and concurrency remain unverified.
2. `hr.employee.location` was readable across OU by an HR officer. Department-related departure records had only native company constraints. Added model-specific rules and target checks; tests cover representative search, read and write paths.
3. Employee names were readable through `resource.resource` and work `res.partner`, and an HR officer could read an employee bank account through `res.partner.bank`. Added scoped restrictions on records linked to employees, preserving unrelated resource, partner and bank examples. A shared contact, bank or resource linked to any inaccessible employee is denied; this may affect non-HR workflows and must be evaluated with their owners. Full cross-application regression is **NOT TESTED**.
4. The security-only relations use `bypass_search_access=True` deliberately so hidden employees cannot masquerade as absent from a linked resource/contact/bank during rule evaluation. They are restricted with `base.group_no_one`; no custom context bypass or monkey patch is used. Tests cover hidden and unassigned employees, ordinary linked records, unrelated records, resource archives and revocation; shared/multiple-employee records and debug-mode interactions need further review.

## Unassigned employee compatibility

The NSTDA-selected upstream rule allows an employee with no operating unit; this implementation preserves visibility according to native Odoo rights and active companies only for employees with no organization history. That never-scoped compatibility is **not fail-closed**; previously scoped employees with no effective OU are fail-closed. No existing employee is auto-assigned. Map employees and verify historical/archived records before production.

## Production readiness

Do not infer complete protection from this audit. Inventory unassigned/archived employees, map and validate units/companies and user assignments, review HR rights and shared contacts/banks/resources, inspect public attachments/tokens, validate remaining employee-related models and downstream modules, restore-test backups, and rehearse upgrade and representative users on a database copy before any rollout. Browser, uninstall, PDF rendering and production migration remain NOT TESTED.

## Multiple employee organizations

Employee and selected related-model restrictions now use primary or effective additional membership overlap; Organization Manager no longer bypasses the employee OU boundary. The policy permits compatibility only for never-scoped employees and fails closed after all scoped OUs become ineffective; see `employee-multi-organization-design.md`. This does not establish complete HR or cross-application confidentiality.
