def migrate(cr, version):
    # Older target AUC fixtures/data could use an expense account with zero
    # years. They were NOT low-value assets under that installed engine.
    # Preserve that economic interpretation rather than silently zeroing them.
    cr.execute("""
        ALTER TABLE account_asset ADD COLUMN IF NOT EXISTS erp_legacy_auc boolean DEFAULT false;
        UPDATE account_asset a SET erp_legacy_auc = true
          FROM account_asset_profile p, account_account account
         WHERE a.profile_id = p.id AND p.account_asset_id = account.id
           AND a.method_number = 0 AND account.account_type = 'expense'
    """)
