# GovOpsDev ERP — Security baseline

Installs with `erp_core` and `auth_signup`. On first installation, public account
registration becomes invitation-only and Odoo's native login cooldown becomes
five failures / 300 seconds. The values are `noupdate`: later administrator
configuration is preserved on module upgrades. Native signup and password-reset
handlers, authentication and access controls remain responsible for enforcement.

This module creates no user, changes no password and grants no permissions. The
requested local evaluation login `admin / admin` is a known-password exception;
replace that password before exposing a deployment outside localhost. Database
and container restrictions are provided by the repository's Docker recipe.

AGPL-3.0-or-later. [Source](https://github.com/GovOpsDev/ERP/)
