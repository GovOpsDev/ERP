#!/usr/bin/env python3
"""Check self-contained demo references and key financial invariants."""
import json
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parents[1] / 'data'
files = ('projects', 'budgets', 'procurement', 'contracts', 'work-acceptance', 'inventory', 'assets')
try:
    data = {name: json.loads((root / f'{name}.json').read_text(encoding='utf-8')) for name in (*files, 'users', 'relationships', 'tour-steps')}
    docs = {}
    for name in files:
        for doc in data[name]:
            assert doc['id'] not in docs, f"duplicate document: {doc['id']}"
            assert all(doc.get(k) for k in ('id', 'kind', 'ref', 'name', 'state', 'company', 'ou')), f"incomplete document {doc}"
            docs[doc['id']] = doc
    users = {u['id']: u for u in data['users']}
    assert len(users) == len(data['users']), 'duplicate user'
    ids = set()
    pairs = set()
    for edge in data['relationships']:
        assert edge['id'] not in ids, f"duplicate relationship {edge['id']}"
        ids.add(edge['id'])
        a, b = docs[edge['from']], docs[edge['to']]
        assert a['company'] == b['company'], f"cross-company relationship {edge['id']}"
        assert a['ou'] == b['ou'], f"cross-OU relationship {edge['id']}"
        assert a.get('project', a['id']) == b.get('project', b['id']), f"cross-project relationship {edge['id']}"
        pairs.add((edge['from'], edge['to']))
    assert {('PR-PC','PO-PC'),('PO-PC','AGR-PC'),('PO-PC','WA-PC'),('WA-PC','BILL-PC'),('BILL-PC','ASSET-PC'),('WA-PAPER','STOCK-PAPER')} <= pairs
    assert ('PO-PC','CON-SERVICE') not in pairs
    for budget in data['budgets']:
        assert budget['amount'] == budget['actual'] + budget['committed'] + budget['remaining'], budget['id']
    assert docs['BUD-001']['actual'] == docs['BILL-PC']['amount'] + docs['BILL-PAPER']['amount']
    assert docs['BUD-001']['committed'] == docs['CON-SERVICE']['amount']
    assert docs['BUD-002']['committed'] == docs['PR-BUILD']['amount']
    stock = docs['STOCK-PAPER']
    assert stock['quantity'] == stock['on_hand'] + stock['destination']
    assert stock['issued'] == stock['destination'] == docs['ISSUE-PAPER']['quantity']
    assert docs['PO-PC']['quantity'] >= docs['WA-PC']['quantity'] >= docs['BILL-PC']['quantity'] >= docs['ASSET-PC']['quantity']
    assert docs['PO-PAPER']['quantity'] >= docs['WA-PAPER']['quantity'] >= docs['BILL-PAPER']['quantity']
    assert docs['WA-PAPER']['quantity'] == stock['quantity']
    assert docs['ASSET-PC']['amount'] == docs['ASSET-PC']['quantity'] * docs['ASSET-PC']['unit_price']
    for doc in docs.values():
        if 'tax' in doc and 'total' in doc:
            assert doc['amount'] + doc['tax'] == doc['total'], doc['id']
    steps = data['tour-steps']
    step_ids = {s['id'] for s in steps}
    assert len(step_ids) == len(steps), 'duplicate step'
    assert sum(s['mode'] == 'main' for s in steps) == 12
    assert sum(s['mode'] == 'permissions' for s in steps) == 4
    for s in steps:
        for key in ('id','title','view','target','tooltip','narration','persona','document_ref','expected_state','next_relationship','duration_hint','mode'):
            assert s.get(key), f"missing {key} in {s.get('id')}"
        assert s['persona'] in users, s['id']
        assert s['document_ref'] in docs or s['document_ref'] == 'COMPANY-PROBE', s['id']
        assert s['next_relationship'] in docs or s['next_relationship'] in step_ids or s['next_relationship'] == 'สิ้นสุด', s['id']
        assert s['target'].startswith('#') and s['duration_hint'] > 0, s['id']
    print(f"OK: {len(docs)} documents, {len(ids)} links, {len(users)} personas, {len(steps)} tour steps")
except (AssertionError, KeyError, OSError, ValueError, TypeError) as exc:
    print(f'INVALID: {exc}', file=sys.stderr)
    sys.exit(1)
