"""Pure direct cash flow from captured journals and approved payable trace."""
import json
from dataclasses import asdict, dataclass

from accounting_harness.domain.ledger import trial_balance
from accounting_harness.financial_reports import FinancialCapture, _capture_financials, financial_statements, _total
from accounting_harness.review import digest


@dataclass(frozen=True, slots=True)
class CashFlowPolicy:
    version: str = 'direct-cash-flow-zero-opening-v1'
    currency: str = 'USD'
    opening_balances: str = 'all_zero'
    cash_account: str = '1000'
    operating_accounts: tuple[str, ...] = ('1100','1200','2100','4000','5000','5100','5200','5300')
    investing_accounts: tuple[str, ...] = ('1500',)
    financing_accounts: tuple[str, ...] = ('3000','3100')
    payable_account: str = '2000'
    payable_expenses: tuple[str, ...] = ('5000','5100')
    bill_policy: str = 'bill-v1'
    payment_policy: str = 'bill-payment-v1'
    supported_form: str = 'one_cash_line_one_counterpart'


@dataclass(frozen=True, slots=True)
class CashFlowCapture:
    financial: FinancialCapture
    payables_json: str
    policy: CashFlowPolicy = CashFlowPolicy()


def capture_cash_flow(ledger, as_of):
    """One read transaction; capture approval facts, never invoke a live service."""
    db = ledger._connection
    with ledger._transaction():
        financial = _capture_financials(ledger, as_of)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

        def rows(sql):
            cursor = db.execute(sql)
            names = [c[0] for c in cursor.description]
            return [{name: str(value) if name.endswith('_cents') else value
                     for name, value in zip(names, row)} for row in cursor]

        bills = rows('SELECT * FROM vendor_bills ORDER BY bill_id') if 'vendor_bills' in tables else []
        payments = rows('SELECT * FROM vendor_bill_payments ORDER BY payment_event_id') if 'vendor_bill_payments' in tables else []
        approval_ids = {r['approval_id'] for r in bills + payments}
        approvals = rows('''SELECT a.*, r.policy_version, p.journal_id FROM approvals a
            JOIN draft_revisions r ON r.draft_id=a.draft_id AND r.revision=a.revision
            LEFT JOIN review_postings p ON p.approval_id=a.approval_id ORDER BY a.approval_id''') if approval_ids else []
        trace = dict(bills=bills, payments=payments,
                     approvals=[a for a in approvals if a['approval_id'] in approval_ids])
        return CashFlowCapture(financial, json.dumps(trace, sort_keys=True, separators=(',',':')))


def _signed(line):
    return line.amount.cents * (1 if line.side == 'debit' else -1)


def _payable_trace(entry, trace, entries, policy):
    """Validate captured settlement and supported bill facts against both journals."""
    payments = [p for p in trace['payments'] if p['journal_id'] == entry.id]
    if len(payments) != 1:
        return None
    payment = payments[0]
    bills = [b for b in trace['bills'] if b['bill_id'] == payment['bill_id']]
    if len(bills) != 1:
        return None
    bill = bills[0]
    result = dict(payment=payment, bill=bill)
    if bill['expense_account'] not in policy.payable_expenses:
        return None
    for name, fact, version in [('payment',payment,policy.payment_policy),('bill',bill,policy.bill_policy)]:
        approved = [a for a in trace['approvals'] if a['approval_id'] == fact['approval_id']]
        if len(approved) != 1:
            return None
        approval = approved[0]
        if digest([approval['binding_json'], approval['actor_id']]) != approval['approval_id']:
            return None
        binding = json.loads(approval['binding_json'])
        expected_sources = {bill['bill_source_id'], payment['cash_source_id'] if name == 'payment' else bill['incurrence_source_id']}
        if (approval['journal_id'] != fact['journal_id'] or approval['policy_version'] != version
            or not approval['actor_id'] or binding.get('policy_version') != version
            or binding.get('entity_id') != entry.entity_id or binding.get('action') != 'post'
            or binding.get('draft_id') != approval['draft_id'] or binding.get('revision') != approval['revision']
            or set(binding.get('evidence', {})) != expected_sources):
            return None
        result[name + '_approval'] = approval
    bill_entry = entries.get(bill['journal_id'])
    if bill_entry is None:
        return None
    principal, paid = int(bill['principal_cents']), int(payment['allocated_cents'])
    if not 0 < paid <= principal or not bill['effective_date'] <= payment['effective_date']:
        return None
    expected_bill = sorted([(bill['expense_account'],'debit',principal),('2000','credit',principal)])
    expected_payment = sorted([('2000','debit',paid),('1000','credit',paid)])
    for journal, expected, effective, sources in [
        (bill_entry,expected_bill,bill['effective_date'],[bill['bill_source_id'],bill['incurrence_source_id']]),
        (entry,expected_payment,payment['effective_date'],[bill['bill_source_id'],payment['cash_source_id']])]:
        if (sorted((l.account,l.side,l.amount.cents) for l in journal.lines) != expected
            or journal.effective_date.isoformat() != effective or sorted(journal.source_ids) != sorted(sources)):
            return None
    return result


def cash_flow_statement(capture):
    """Render exact signed flows, explicit exceptions and an independent Cash bridge."""
    if not isinstance(capture, CashFlowCapture):
        raise TypeError('cash flow requires a CashFlowCapture')
    if capture.policy != CashFlowPolicy():
        raise ValueError('unsupported cash-flow policy')
    statements = financial_statements(capture.financial)
    snapshot, cutoff, policy = capture.financial.ledger, capture.financial.as_of, capture.policy
    if (snapshot.period_start.isoformat(), snapshot.period_end.isoformat()) != ('2026-01-01','2026-01-31'):
        raise ValueError('cash-flow policy supports only the synthetic January 2026 period')
    trace = json.loads(capture.payables_json)
    contexts = {j.journal_id:j for j in capture.financial.journals}
    entries = {e.id:e for e in snapshot.entries}
    policy_data = asdict(policy)
    captured = dict(kind='direct_cash_flow',schema_version=1,financial=statements['capture'],
                    payables=trace,policy=policy_data)
    report = dict(statement='cash_flow',entity_id=snapshot.catalog.entity_id,currency='USD',
        period_start=snapshot.period_start.isoformat(),period_end=snapshot.period_end.isoformat(),as_of=cutoff.isoformat(),
        catalog=statements['catalog'],policy=policy_data,policy_digest=digest(policy_data),
        financial_snapshot_digest=statements['snapshot_digest'],snapshot_digest=digest(captured),
        included_journal_ids=statements['included_journal_ids'],
        excluded_closing_journal_ids=statements['excluded_closing_journal_ids'],capture=captured,rows=[],exceptions=[])
    totals = dict(operating=0,investing=0,financing=0,unresolved=0,operating_receipts=0,operating_payments=0)
    for entry in sorted(snapshot.entries,key=lambda e:(e.effective_date,e.id)):
        cash = [l for l in entry.lines if l.account == policy.cash_account]
        if entry.effective_date > cutoff or not cash:
            continue
        counterpart = [l for l in entry.lines if l.account != policy.cash_account]
        amount = sum(_signed(l) for l in cash)
        row = dict(asdict(contexts[entry.id]),effective_date=entry.effective_date.isoformat(),
                   description=entry.description,source_ids=list(entry.source_ids),category='unresolved',
                   cash_lines=[dict(account=l.account,side=l.side,posted_amount=str(l.amount),cents=str(l.amount.cents)) for l in cash],
                   counterparts=[dict(account=l.account,side=l.side,posted_amount=str(l.amount),cents=str(l.amount.cents)) for l in counterpart])
        _total(row,'cash',amount)
        reason = None
        if contexts[entry.id].classification == 'closing':
            reason = ('closing_cash','Closing journal contains Cash; integrity review required.')
        elif len(cash) != 1 or len(counterpart) != 1:
            reason = ('unsupported_form','Requires exactly one Cash line and one non-Cash counterpart; no allocation inferred.')
        else:
            account = counterpart[0].account
            if account == policy.payable_account:
                basis = entry
                original = contexts[entry.id].original_entry_id
                if original:
                    basis = entries.get(original)
                    if basis is None or sorted((l.account,_signed(l)) for l in basis.lines) != sorted((l.account,-_signed(l)) for l in entry.lines):
                        basis = None
                approved_trace = _payable_trace(basis,trace,entries,policy) if basis else None
                if approved_trace:
                    row['category']='operating';row['payable_trace']=approved_trace
                else:
                    reason=('unsupported_payable','Missing, contradictory or unsupported captured approved bill/payment trace.')
            elif any(p['journal_id']==entry.id for p in trace['payments']) or any(b['journal_id']==entry.id for b in trace['bills']):
                reason=('contradictory_payable','Captured payable evidence contradicts this cash counterpart.')
            else:
                for category in ('operating','investing','financing'):
                    if account in getattr(policy,category+'_accounts'):
                        row['category']=category
                        break
                if row['category']=='unresolved':
                    reason=('unsupported_counterpart','Counterpart is outside the captured classification policy.')
        if reason:
            row['exception_code'],row['exception']=reason
            report['exceptions'].append(dict(journal_id=entry.id,code=reason[0],message=reason[1],
                                               cash_cents=row['cash_cents'],cash_amount=row['cash_amount']))
        report['rows'].append(row)
        totals[row['category']] += amount
        if row['category']=='operating':
            totals['operating_receipts' if amount > 0 else 'operating_payments'] += amount
    # The closing Cash is read from the full ledger independently of categorization.
    balance = next(r for r in trial_balance(snapshot,cutoff).rows if r.account==policy.cash_account)
    ending = balance.debit.cents - balance.credit.cents
    change = sum(totals[k] for k in ('operating','investing','financing','unresolved'))
    for name,value in dict(totals,opening_cash=0,net_change=change,ending_cash=ending,residual=ending-change).items():
        _total(report,name,value)
    report['reconciled'] = ending == change
    report['classification_complete'] = not report['exceptions'] and report['reconciled']
    report['report_digest'] = digest(report)
    return report


def demo_cash_flow():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='cash-flow-demo-') as directory:
        workspace=Workspace(directory);build_adjusted_month(workspace)
        report=workspace.cash_flow('2026-01-31')
        assert [report[k+'_amount'] for k in ('operating','investing','financing','ending_cash','residual')] == ['-400.00','0.00','9800.00','9400.00','0.00']
        assert report['classification_complete']
        print('Captured direct cash flow · USD · through',report['as_of'])
        for label,key in [('Operating receipts','operating_receipts'),('Operating payments','operating_payments'),
            ('Operating','operating'),('Investing','investing'),('Financing','financing'),('Opening Cash','opening_cash'),
            ('Net change','net_change'),('Ending Cash','ending_cash'),('Residual','residual')]:
            print(label+':',report[key+'_amount'])
        print('Classification complete:',report['classification_complete'])
        print('Snapshot:',report['snapshot_digest'],'Policy:',report['policy_digest'])
        print('Cash journals:',len(report['rows']),'Report:',report['report_digest'])
