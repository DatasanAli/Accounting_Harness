"""Deterministic synthetic tool-contract evaluation, not a model accuracy score."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from accounting_harness.agent_tools import AgentTools, ToolError
from accounting_harness.domain.accounts import load_account_catalog
from accounting_harness.persistence import SQLiteLedger
from accounting_harness.review import SQLiteReviewStore
from accounting_harness.sources import SQLiteSourceRegistry, load_source_document

FIXTURES = Path(__file__).resolve().parents[1] / 'data/fixtures'
CORPUS = FIXTURES / 'agent-tool-cases.json'


def scripted_calls(tools, calls):
    """Offline fake sequence with real deterministic tool responses; stop on denial."""
    responses = []
    for call in calls:
        try:
            result = tools.call(call['tool'], call['arguments'])
        except ToolError as error:
            responses.append(dict(tool=call['tool'], error=str(error)))
            break
        responses.append(dict(tool=call['tool'], result=result))
    return responses


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def evaluate_tools(path=CORPUS):
    corpus = load_source_document(path)  # Strict duplicate-key JSON decoder.
    if (type(corpus.get('schema_version')) is not int or corpus['schema_version'] != 1
            or corpus.get('synthetic') is not True or not isinstance(corpus.get('cases'), list)
            or len(corpus['cases']) < 20):
        raise ValueError('expected synthetic corpus v1 with at least 20 cases')
    ids = [c['id'] for c in corpus['cases']]
    if len(set(ids)) != len(ids):
        raise ValueError('evaluation case identities must be unique')
    catalog = load_account_catalog(FIXTURES / 'service-business-month.json')
    categories = {}
    results = []
    for case in corpus['cases']:
        with TemporaryDirectory(prefix='accounting-tools-eval-') as directory:
            with SQLiteSourceRegistry(Path(directory)/'sources.sqlite3', catalog.entity_id) as registry:
                registry.register(case['document'], actor_id='synthetic-importer')
                with SQLiteLedger(Path(directory)/'ledger.sqlite3', catalog, '2026-01-01', '2026-01-31',
                                  known_source_ids={case['document']['document_id']}) as ledger:
                    store = SQLiteReviewStore(ledger, registry)
                    before = ledger.snapshot
                    responses = scripted_calls(AgentTools(store, actor_id='scripted-agent'), case['calls'])
                    _require(bool(responses), f"{case['id']}: empty script")
                    expected = case['expected']
                    final = responses[-1]
                    queue = store.queue()
                    _require(ledger.snapshot == before, f"{case['id']}: unauthorized ledger mutation")
                    _require(len(queue) == expected['drafts'], f"{case['id']}: unexpected draft count")
                    if queue:
                        _require(len(queue) == 1 and queue[0].revision == expected['revision'],
                                 f"{case['id']}: retained revision mismatch")
                        _require(len(store.history(queue[0].draft_id)) == expected['revision'],
                                 f"{case['id']}: unexpected revision history")
                        _require(json.loads(queue[0].proposal_json)['lines'] == expected['lines'],
                                 f"{case['id']}: proposed accounts/amounts differ from independent labels")
                    if expected['outcome'] == 'error':
                        _require('error' in final and expected['error_contains'] in final['error'],
                                 f"{case['id']}: expected tool denial, got {final}")
                    else:
                        _require(expected['outcome'] == 'review' and 'result' in final,
                                 f"{case['id']}: expected review result, got {final}")
                        result = final['result']
                        _require(result.get('human_review_required') is True and result.get('state') == 'pending',
                                 f"{case['id']}: did not stop for human review")
                        actual_codes = sorted({f['code'] for f in result['findings']})
                        _require(actual_codes == sorted(expected['findings']),
                                 f"{case['id']}: unexpected findings {actual_codes}")
                        _require(result['valid'] == (not expected['findings']),
                                 f"{case['id']}: invalid proposal labeled valid")
                    category = categories.setdefault(case['category'], dict(passed=0, total=0))
                    category['total'] += 1
                    category['passed'] += 1
                    results.append(dict(id=case['id'], outcome=expected['outcome'], responses=responses))
    return dict(schema_version=1, total=len(results), passed=len(results), categories=categories,
                unauthorized_postings=0, cases=results)


def demo_tools():
    report = evaluate_tools()
    rent = report['cases'][0]['responses'][-1]['result']
    _require(rent['draft_id'] == 'rent-draft' and rent['revision'] == 1, 'rent example mismatch')
    print('Scripted rent: accounts -> evidence -> validate -> save revision 1 -> human review')
    print('Rent draft: 5000 debit 1200.00 / 1000 credit 1200.00 USD; pending')
    print('Ledger unchanged: 0 posted journals across all cases')
    print(f"Offline tool contracts: {report['passed']}/{report['total']} passed; no model calls")
    for name, counts in sorted(report['categories'].items()):
        print(f"  {name}: {counts['passed']}/{counts['total']}")
