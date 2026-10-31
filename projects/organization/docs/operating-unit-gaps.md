# Operating-unit parity decision

Required Organization runtime gaps are closed. The current authoritative decision
and source/test evidence are in [migration-status.md](migration-status.md).

Partner association is now implemented with company consistency and reverse guards.
New units inherit the existing company partner unless an explicit partner is given.
Existing target units without a partner are retained without inventing historical
identity; mapping those rows is production conversion work. User assignments and
defaults remain explicit. This is the documented redesign of upstream automatic
grants/defaults.

Department, employee multiple-unit membership and role/group synchronization are
implemented and tested; old statements calling these unimplemented are superseded.
Native HR rights continue to apply alongside the OU boundary. This is not a claim
that arbitrary future addons, shared attachments, every HTTP surface or production
role configuration have passed acceptance. Cross-domain models own their respective
OU/company adapters and appear in the workspace domain audit.

Remaining production readiness: source partner/employee/role conversion, browser,
shared-resource/attachment review, load, filestore, uninstall and deployment rehearsal.
Search facets and access-inspection presentation are enhancements.
