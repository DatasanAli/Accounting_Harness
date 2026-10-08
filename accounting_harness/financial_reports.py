"""Read-only, zero-opening owner statements derived from one immutable capture."""

from dataclasses import asdict, dataclass
from datetime import date

from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.ledger import LedgerSnapshot
from accounting_harness.domain.money import Money
from accounting_harness.review import digest


@dataclass(frozen=True, slots=True)
class FinancialPolicy:
    version: str = 'owner-statements-zero-opening-v1'
    basis: str = 'accrual'
    equity_model: str = 'owner_capital_and_drawings'
    opening_balances: str = 'all_zero'
    currency: str = 'USD'
    capital_account: str = '3000'
    drawings_account: str = '3100'
    included_classification: str = 'ordinary'
    excluded_classification: str = 'closing'


@dataclass(frozen=True, slots=True)
class JournalContext:
    journal_id: str
    classification: str
    actor_id: str
    recorded_at: str
    original_entry_id: str | None


@dataclass(frozen=True, slots=True)
class FinancialCapture:
    ledger: LedgerSnapshot
    as_of: date
    journals: tuple[JournalContext, ...]
    policy: FinancialPolicy


def _validate(capture):
    if not isinstance(capture, FinancialCapture):
        raise TypeError('financial statements require a FinancialCapture')
    if capture.policy != FinancialPolicy():
        raise ValueError('unsupported financial statement policy; only zero-opening accrual owner statements in USD')
    if capture.ledger.catalog.currency != 'USD':
        raise ValueError('financial statements support only USD')
    cutoff = accounting_date(capture.as_of)
    if not capture.ledger.period_start <= cutoff <= capture.ledger.period_end:
        raise ValueError('report cutoff must be inside the inclusive captured ledger period')
    contexts = {j.journal_id: j for j in capture.journals}
    if len(contexts) != len(capture.journals) or set(contexts) != {e.id for e in capture.ledger.entries}:
        raise ValueError('capture requires exactly one classification for every journal')
    if any(j.classification not in ('ordinary','closing') for j in capture.journals):
        raise ValueError('unsupported journal classification')
    equity = {a.code for a in capture.ledger.catalog.accounts if a.classification == 'equity'}
    if equity != {capture.policy.capital_account, capture.policy.drawings_account}:
        raise ValueError('unsupported equity accounts for owner capital and drawings policy')


def capture_financials(ledger, as_of, *, basis='accrual', equity_model='owner_capital_and_drawings',
                       opening_balances='all_zero', currency='USD'):
    """Capture ledger and durable closing classifications in one read transaction."""
    policy = FinancialPolicy(basis=basis, equity_model=equity_model,
                             opening_balances=opening_balances, currency=currency)
    with ledger._transaction():
        return _capture_financials(ledger, as_of, policy)


def _capture_financials(ledger, as_of, policy=FinancialPolicy()):
    """Shared transaction boundary for financial reports and close confirmation."""
    snapshot = ledger._snapshot()
    closing = {r[0] for r in ledger._connection.execute('SELECT journal_id FROM period_closes WHERE journal_id IS NOT NULL')}
    journals = []
    for entry in snapshot.entries:
        receipt = ledger._receipt(entry.id)
        journals.append(JournalContext(entry.id, 'closing' if entry.id in closing else 'ordinary', receipt.actor_id,
                                       receipt.recorded_at.isoformat(), receipt.original_entry_id))
    capture = FinancialCapture(snapshot, accounting_date(as_of), tuple(journals), policy)
    _validate(capture)
    return capture


def _amount(cents):
    return ('-' if cents < 0 else '') + str(Money(abs(cents)))


def _total(target, name, cents):
    target[name + '_cents'] = str(cents)
    target[name + '_amount'] = _amount(cents)


def financial_statements(capture):
    """Pure rendering of all three linked statements; no ledger/registry queries.

    All cent fields crossing the JSON boundary are strings; calculation uses
    Python integers. Normal balance never suppresses an opposite-side balance.
    """
    _validate(capture)
    snapshot, policy = capture.ledger, asdict(capture.policy)
    contexts = {j.journal_id: j for j in capture.journals}
    entries = sorted(snapshot.entries, key=lambda e: (e.effective_date, e.id))
    captured = dict(entity_id=snapshot.catalog.entity_id, currency=snapshot.catalog.currency,
        period_start=snapshot.period_start.isoformat(), period_end=snapshot.period_end.isoformat(),
        catalog=[asdict(a) for a in snapshot.catalog.list_accounts()], policy=policy,
        entries=[dict(journal_id=e.id, entity_id=e.entity_id, currency=e.currency,
            effective_date=e.effective_date.isoformat(), description=e.description,
            source_ids=list(e.source_ids), context=asdict(contexts[e.id]),
            lines=[dict(account=l.account,side=l.side,cents=str(l.amount.cents),amount=str(l.amount)) for l in e.lines])
            for e in entries])
    included = [e for e in entries if snapshot.period_start <= e.effective_date <= capture.as_of
                and contexts[e.id].classification == 'ordinary']
    metadata = dict(entity_id=snapshot.catalog.entity_id, currency=snapshot.catalog.currency,
        period_start=snapshot.period_start.isoformat(), period_end=snapshot.period_end.isoformat(),
        as_of=capture.as_of.isoformat(), catalog=captured['catalog'], policy=policy,
        policy_digest=digest(policy), snapshot_digest=digest(captured),
        included_journal_ids=[e.id for e in included],
        excluded_closing_journal_ids=[e.id for e in entries if e.effective_date <= capture.as_of
                                     and contexts[e.id].classification == 'closing'])
    rows = {}
    for account in snapshot.catalog.list_accounts():
        # Owner drawings are the explicit debit-side equity movement.
        debit_positive = account.classification in ('asset','expense') or account.code == capture.policy.drawings_account
        drilldown = []
        for entry in included:
            for position, line in enumerate(entry.lines, 1):
                if line.account != account.code:
                    continue
                net = line.amount.cents * (1 if (line.side == 'debit') == debit_positive else -1)
                drilldown.append(dict(asdict(contexts[entry.id]), line_number=position,
                    effective_date=entry.effective_date.isoformat(), description=entry.description,
                    source_ids=list(entry.source_ids), side=line.side,
                    posted_amount=str(line.amount), net_cents=str(net), amount=_amount(net)))
        net = sum(int(line['net_cents']) for line in drilldown)
        rows[account.code] = dict(account=account.code,name=account.name,
            classification=account.classification,normal_side=account.normal_side,
            net_cents=str(net),amount=_amount(net),drilldown=drilldown)

    def selected(kind):
        return [row for row in rows.values() if row['classification'] == kind]

    def summed(selected_rows):
        return sum(int(row['net_cents']) for row in selected_rows)

    income = dict(metadata, statement='income_statement', revenue=selected('revenue'), expenses=selected('expense'))
    revenue, expenses = summed(income['revenue']), summed(income['expenses'])
    net_income = revenue - expenses
    for name,value in [('revenue',revenue),('expenses',expenses),('net_income',net_income)]:
        _total(income,name,value)
    income['report_digest'] = digest(income)

    contributions, drawings = rows[capture.policy.capital_account], rows[capture.policy.drawings_account]
    capital, withdrawn = int(contributions['net_cents']), int(drawings['net_cents'])
    ending_equity = capital + net_income - withdrawn
    equity = dict(metadata,statement='owners_equity',contributions=contributions,drawings=drawings,
                  income_statement_digest=income['report_digest'])
    for name,value in [('opening_capital',0),('contributions',capital),('net_income',net_income),
                       ('drawings',withdrawn),('ending_equity',ending_equity)]:
        _total(equity,name,value)
    equity['report_digest'] = digest(equity)

    balance = dict(metadata,statement='balance_sheet',assets=selected('asset'),liabilities=selected('liability'),
                   owners_equity_digest=equity['report_digest'])
    assets, liabilities = summed(balance['assets']), summed(balance['liabilities'])
    residual = assets - liabilities - ending_equity
    for name,value in [('assets',assets),('liabilities',liabilities),('equity',ending_equity),('residual',residual)]:
        _total(balance,name,value)
    balance['reconciled'] = residual == 0
    balance['report_digest'] = digest(balance)
    report = dict(metadata,capture=captured,income_statement=income,owners_equity=equity,balance_sheet=balance)
    report['report_digest'] = digest(report)
    return report


def demo_statements():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='statements-demo-') as directory:
        workspace = Workspace(directory)
        build_adjusted_month(workspace)
        report = workspace.financial_statements('2026-01-31')
        income,equity,balance = (report[k] for k in ('income_statement','owners_equity','balance_sheet'))
        assert (income['revenue_amount'],income['expenses_amount'],income['net_income_amount']) == ('2700.00','1600.00','1100.00')
        assert (balance['assets_amount'],balance['liabilities_amount'],balance['equity_amount']) == ('11500.00','600.00','10900.00')
        assert balance['reconciled']
        print('Captured owner statements · inclusive cutoff',report['as_of'])
        print('Revenue:',income['revenue_amount'],'Expenses:',income['expenses_amount'],'Income:',income['net_income_amount'])
        print('Opening:',equity['opening_capital_amount'],'Net contributions:',equity['contributions_amount'],
              'Net drawings:',equity['drawings_amount'],'Ending equity:',equity['ending_equity_amount'])
        print('Assets:',balance['assets_amount'],'Liabilities:',balance['liabilities_amount'],'Equity:',balance['equity_amount'])
        print('Residual:',balance['residual_amount'],'USD; reconciled:',balance['reconciled'])
        print('Snapshot:',report['snapshot_digest'],'Policy:',report['policy_digest'])
        print('Journals:',len(report['included_journal_ids']),'Report:',report['report_digest'])
