"""Refresh only the two OCA asset package descriptions in an Odoo shell.

Some existing module metadata is noupdate. Force-overwrite is intentionally
limited to these two XML IDs and the Thai language; business records are untouched.
Run with an explicitly selected database and a verified backup.
"""
from odoo.tools.translate import TranslationImporter

modules = ('account_asset_management', 'account_asset_transfer')
xmlids = {'base.module_' + name for name in modules}
for xmlid in xmlids:
    env.ref(xmlid)  # Fail before writing when a required module is absent.
importer = TranslationImporter(env.cr)
for module in modules:
    importer.load_file(module + '/i18n_extra/th.po', 'th_TH', xmlids=xmlids)
importer.save(overwrite=True, force_overwrite=True)
for module in modules:
    record = env.ref('base.module_' + module)
    record.invalidate_recordset(['description'])
    assert 'โมดูลนี้' in record.with_context(lang='th_TH').description, module
env.cr.commit()
print('Thai OCA package descriptions refreshed:', ', '.join(modules))
