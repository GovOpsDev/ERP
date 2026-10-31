# History and provenance

The former root repository retains branch `pre-workspace-refactor` at original commit `d09684da7bfb5c33df4081cfa07160aebf8d5f91` (`feat: add company-scoped organization structure`). `git subtree split --prefix=addons/erp_base_organization d09684d` produced `7b96e3eaebf328d62352bf5f4f67133e832e1670`, which is the initial ancestor of this independent repository. The following refactor commit moves and renames the addon while preserving that ancestor. No upstream source code was copied; upstream behavior and licenses are mapped in `organization-discovery.md`.
