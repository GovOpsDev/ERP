#!/usr/bin/env python3
"""Validate Thai UI catalogs and, optionally, source coverage from Odoo POT exports.

Run inside the pinned Odoo image, which includes polib. POT files are exported by
`odoo i18n export -l pot` from an installed reference database. No DB is changed.
"""
import argparse
from collections import Counter
from pathlib import Path
import re

import polib

ROOT = Path(__file__).resolve().parents[2]
CUSTOM = {
    path.parent.name: path.parent / 'i18n' / 'th.po'
    for path in list((ROOT / 'projects').glob('*/addons/erp_*/__manifest__.py'))
    + list((ROOT / 'shared/erp_core/addons').glob('erp_*/__manifest__.py'))
}
OCA = {
    name: ROOT / 'projects/asset/addons' / name / 'i18n_extra/th.po'
    for name in ('account_asset_management', 'account_asset_transfer')
}
EXTRA = ROOT / 'shared/erp_core/addons/erp_core/i18n_extra/th.po'
PLACEHOLDER = re.compile(
    r'%(?:\([^)]+\))?[#0 +\-]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[hlL]?[diouxXeEfFgGcrsa]'
    r'|\{[A-Za-z_][\w.]*\}'
)
THAI = re.compile(r'[ก-๙]')
MACHINE_KEYS = {'degr-limit', 'degr-linear', 'degressive', 'gain_loss_on_sale', 'linear-limit', 'number', 'quarter', 'year'}

parser = argparse.ArgumentParser()
parser.add_argument('--custom-pot', type=Path)
parser.add_argument('--oca-pot', type=Path)
args = parser.parse_args()
files = {**CUSTOM, **OCA, 'core_extra': EXTRA}
po = {}
entry_count = 0
for module, path in files.items():
    assert path.is_file(), f'Missing catalog: {path}'
    catalog = polib.pofile(str(path), check_for_duplicates=True)
    assert catalog.metadata.get('Language') == 'th_TH', path
    for entry in catalog:
        assert entry.msgstr and not entry.msgid_plural and 'fuzzy' not in entry.flags, (path, entry.msgid)
        assert Counter(PLACEHOLDER.findall(entry.msgid)) == Counter(PLACEHOLDER.findall(entry.msgstr)), (path, entry.msgid)
        if any(ref.startswith('code:') for ref, _ in entry.occurrences):
            assert 'odoo-python' in entry.comment or 'odoo-javascript' in entry.comment, (path, entry.msgid)
    po[module] = catalog
    entry_count += len(catalog)


def verify_export(path, modules, exclusions=()):
    source = polib.pofile(str(path), check_for_duplicates=True)
    missing = []
    for entry in source:
        if THAI.search(entry.msgid) or entry.msgid in exclusions:
            continue
        if entry.msgid.startswith('<span ') and re.sub(r'<[^>]+>|[%\s]', '', entry.msgid) == '':
            continue
        owners = {name for name in modules if re.search(r'\b' + re.escape(name) + r'\b', entry.comment)}
        for module in owners:
            refs = {(ref, line) for ref, line in entry.occurrences if (
                f':{module}.' in ref or f'/{module}/' in ref or
                ref.startswith(f'code:{module}/') or f':base.module_{module}' in ref
            )}
            found = po[module].find(entry.msgid)
            if not refs or not found or not refs.issubset(set(found.occurrences)):
                missing.append((module, entry.msgid))
    assert not missing, f'Untranslated or missing source references: {missing[:15]}'
    return len(source)

result = {'catalogs': len(files), 'translated_entries': entry_count, 'placeholder_errors': 0}
if args.custom_pot:
    result['custom_source_entries'] = verify_export(args.custom_pot, CUSTOM, {'id'})
if args.oca_pot:
    result['asset_source_entries'] = verify_export(args.oca_pot, OCA, MACHINE_KEYS)
print(result)
