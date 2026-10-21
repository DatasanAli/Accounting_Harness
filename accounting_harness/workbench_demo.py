"""Temporary synthetic HTTP rehearsal; no live provider or external connection."""
import http.client
import json
import re
import threading
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.access import AccessStore, provision_synthetic_workspace
from accounting_harness.web import make_server


def demo_workbench():
    with TemporaryDirectory(prefix='accounting-workbench-') as directory:
        root = Path(directory)
        access = AccessStore(root / 'access.sqlite3')
        provision_synthetic_workspace(root / 'alpha', 'alpha')
        access.register_entity('alpha', root / 'alpha', reason='Synthetic workbench demonstration')
        users = {}
        for role in ('preparer', 'reviewer'):
            users[role] = access.create_user(role, 'Synthetic workbench passphrase ' + role,
                reason='Synthetic workbench demonstration')
            access.bootstrap_grant(users[role], 'alpha', role, reason='Synthetic demonstration', retry_key=role)
        with make_server(access_db=access.path, port=0) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            sessions = {role: dict(cookie='', csrf='', entity='') for role in users}

            def request(role, path, data=None, expected=200):
                session = sessions[role]
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=15)
                try:
                    connection.request('GET' if data is None else 'POST', path,
                        json.dumps(data) if data is not None else None,
                        {'Origin': 'http://127.0.0.1:' + str(server.server_port),
                         'Content-Type': 'application/json', 'Cookie': session['cookie'],
                         'X-CSRF-Token': session['csrf'], 'X-Entity-ID': session['entity']})
                    response = connection.getresponse()
                    raw = response.read()
                    result = json.loads(raw) if 'application/json' in response.getheader('Content-Type', '') else raw.decode()
                    assert response.status == expected, (path, response.status, result)
                    for key, value in response.getheaders():
                        if key.lower() == 'set-cookie' and not 'Max-Age=0' in value:
                            session['cookie'] = value.split(';')[0]
                    return result
                finally:
                    connection.close()

            try:
                html = request('preparer', '/')
                groups = set(re.findall(r'data-group="([^"]+)"', html))
                assert groups == {'prepare', 'review', 'ledger', 'period', 'planning', 'operations'}, groups
                for role in users:
                    session = sessions[role]
                    session['csrf'] = request(role, '/api/login-challenge')['csrf_token']
                    request(role, '/api/login', dict(username=role, password='Synthetic workbench passphrase ' + role))
                    session['csrf'] = request(role, '/api/session')['csrf_token']
                    selected = request(role, '/api/entity', dict(entity_id='alpha'))
                    session.update(csrf=selected['csrf_token'], entity='alpha')
                state = request('preparer', '/api/state')
                assert state['journal_count'] == 0
                assert 'approve-post' not in state['allowed_actions']
                assert [p['id'] for p in state['providers'] if p['available']] == ['offline']
                common = dict(schema_version=2, synthetic=True, entity_id='alpha', currency='USD',
                    document_date='2026-01-05', amount='125.00', event_id='workbench-rent',
                    counterparty='Fictional landlord', counterparty_id='landlord', description='Synthetic January rent')
                for document in (
                    dict(common, document_id='rent-cash', kind='cash_movement', direction='out', purpose='incurred_expense'),
                    dict(common, document_id='rent-fact', kind='incurred_expense', incurred_date='2026-01-05', expense_account='5000')):
                    request('preparer', '/api/operation-sources', dict(document=document))
                payload = dict(operation='cash_expense', cash_source_id='rent-cash', recognition_source_id='rent-fact')
                draft = request('preparer', '/api/cash-proposals', payload)
                assert request('preparer', '/api/cash-proposals', payload) == draft
                confirmation = dict(draft_id=draft['draft_id'], revision=draft['revision'], confirmed_digest=draft['content_digest'])
                request('preparer', '/api/approve-post', confirmation, expected=403)
                assert request('reviewer', '/api/state')['journal_count'] == 0
                posted = request('reviewer', '/api/approve-post', confirmation)
                assert request('reviewer', '/api/approve-post', confirmation) == posted
                after = request('reviewer', '/api/state')
                assert after['journal_count'] == 1 and after['trial_balance']['total_debits'] == '125.00'
                trace = after['drafts'][0]
                assert trace['audit']['approval']['actor_id'] == users['reviewer']
                assert trace['history'][0]['actor'] == users['preparer']
                assert trace['audit']['journal_id'] == posted['journal_id']
                assert set(trace['evidence']) == {'rent-cash', 'rent-fact'}
                report = request('reviewer', '/api/financial-statements?as_of=2026-01-31')
                assert posted['journal_id'] in str(report)
                print('Workbench: 6 task groups; authenticated entity, identity, role and offline provider context.')
                print('HTTP preparer denial 403; 0 journals until separate reviewer approval; then one 125.00 USD journal.')
                print('Exact retry and source → revision → approval → journal → report trace verified. No live calls.')
                print('Presentation/route contract only; native keyboard and viewport rehearsal is recorded separately.')
            finally:
                server.shutdown()
                thread.join()
