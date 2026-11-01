# Upstream baseline

- Repository: https://github.com/NSTDA/ERP-Government
- Branch: `main`; commit: `5a1722c4c6f6cfdf3ed59362a56e85777c58a383`; inspected 2026-10-29 (Asia/Bangkok).
- Reference checkout: `../upstream/ERP-Government` (outside project Git tree).
- Odoo: **15.0**, evidenced independently by the README badge, 14 private manifests with `15.0` versions, and `odoo/custom/src/repos.yaml` merge references. `om_credit_limit` declares `4.3.0`, not an Odoo series.
- Root license: AGPL-3.0; 14 of 15 checked manifests declare AGPL-3 and `om_credit_limit` declares LGPL-3. See license review.
- 15 local addon manifests: identified in the upstream source. `odoo/custom/src/addons.yaml` selects many external modules, and `repos.yaml` describes external OCA/other remotes and merge commits. These are not present in this checkout; its root revision alone does not pin a complete assembled build. Runtime variables and build recipe must be resolved before reproducing that source.
- Layout: deployment YAML and Doodba configuration at root; private addons in `odoo/custom/src/private`; external selection and merge instructions under `odoo/custom/src`. No source or business data was changed in upstream.
