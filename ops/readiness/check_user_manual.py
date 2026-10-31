#!/usr/bin/env python3
"""Check HTML guides, navigation, images and Odoo menu declarations without Odoo."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import ast
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / 'shared/erp_core/addons/erp_user_manual'
MANUAL = ADDON / 'static/manual'

class Document(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path, self.ids, self.links, self.errors = path, set(), [], []
        self.lang, self.title, self.h1 = None, False, 0
        self.images = 0
    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == 'html': self.lang = data.get('lang')
        if tag == 'title': self.title = True
        if tag == 'h1': self.h1 += 1
        if 'id' in data:
            if data['id'] in self.ids: self.errors.append('duplicate id: ' + data['id'])
            self.ids.add(data['id'])
        if tag == 'img':
            self.images += 1
            if not data.get('alt', '').strip(): self.errors.append('image missing alt')
        for key in ('href', 'src'):
            if data.get(key): self.links.append(data[key])

def check():
    guides = json.loads((MANUAL / 'guides.json').read_text())
    assert len(guides) == len({g['key'] for g in guides}) == 15
    documents = {}
    for path in MANUAL.glob('*.html'):
        doc = Document(path)
        doc.feed(path.read_text())
        assert doc.lang == 'th' and doc.title and doc.h1 == 1, path.name
        assert not doc.errors, (path.name, doc.errors)
        documents[path.resolve()] = doc
    assert len(documents) == 16
    assert all('currency-faq' in doc.ids and '#currency-faq' in doc.links for doc in documents.values()), 'Currency FAQ or navigation missing'
    references = 0
    for path, doc in documents.items():
        for link in doc.links:
            url = urlsplit(link)
            assert not url.scheme and not url.netloc, (path.name, 'unexpected external resource', link)
            if url.path == '/odoo': continue
            assert not url.path.startswith('/'), (path.name, link)
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            assert target.is_relative_to(MANUAL.resolve()), (path.name, link)
            assert target.is_file(), (path.name, 'missing file', link)
            if url.fragment:
                assert target in documents and unquote(url.fragment) in documents[target].ids, (path.name, 'missing anchor', link)
            references += 1
    tree = ET.parse(ADDON / 'views/manual_menus.xml')
    menus, actions = tree.findall('menuitem'), tree.findall('record')
    assert len(menus) == len(actions) == 15
    by_key = {g['key']: g for g in guides}
    for menu in menus:
        key = menu.get('id').removeprefix('menu_manual_')
        assert menu.get('parent') == by_key[key]['parent']
        assert menu.get('name') == 'คู่มือการใช้งาน'
        assert menu.get('groups') and menu.get('sequence') == '990'
    for action in actions:
        key = action.get('id').removeprefix('action_manual_')
        fields = {x.get('name'): x.text for x in action.findall('field')}
        assert action.get('model') == 'ir.actions.act_url'
        assert fields['target'] == 'new'
        assert fields['url'].split('?')[0] == '/erp_user_manual/static/manual/' + key + '.html'
    manifest = ast.literal_eval((ADDON / '__manifest__.py').read_text())
    assert manifest['data'] == ['views/manual_menus.xml'] and not manifest['application']
    return {'guides': len(guides), 'html_pages': len(documents), 'menus': len(menus),
            'images': sum(d.images for d in documents.values()), 'checked_local_references': references,
            'currency_faq_pages': sum('currency-faq' in d.ids for d in documents.values())}

if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False))
