"""Completed, unbilled and uncollected service recognition at January cutoff."""
from contextlib import nullcontext
from dataclasses import dataclass

from accounting_harness.expense_accrual import (
    ExpenseAccrualService, _accrual_report, expense_accrual_report,
    prepare_expense_accrual_post as prepare_revenue_accrual_post,
)
from accounting_harness.review import digest

POLICY = 'revenue-accrual-v1'


class RevenueAccrualService(ExpenseAccrualService):
    policy_version = POLICY

    def __init__(self,ledger,registry):
        # Own all shared upgrades before any service can commit them separately.
        with (nullcontext() if ledger._connection.in_transaction else ledger._transaction(write=True)):
            ledger._migrate_v6()
            ExpenseAccrualService(ledger,registry)
            super().__init__(ledger,registry)

    def propose(self,*,completion_source_id,basis_source_id,expected_revision,actor_id,idempotency_key):
        return self._propose(completion_source_id,basis_source_id,expected_revision,actor_id,idempotency_key)

    def combined_snapshot(self):
        with self.ledger._transaction():
            return AccrualSnapshot(self._snapshot(policy='expense-accrual-v1'),self._snapshot())


@dataclass(frozen=True,slots=True)
class AccrualSnapshot:
    expenses: object
    revenue: object


def revenue_accrual_report(snapshot,*,as_of):
    return _accrual_report(snapshot,as_of=as_of,policy=POLICY)


def accrual_report(snapshot,*,as_of):
    """Explicit v2 combined capture, including captures without revenue effects."""
    expenses=expense_accrual_report(snapshot.expenses,as_of=as_of)
    revenue=revenue_accrual_report(snapshot.revenue,as_of=as_of)
    report=dict(schema_version=2,report_policy='outstanding-accruals-v2',as_of=expenses['as_of'],
                expenses=expenses,revenue=revenue,
                snapshot_digest=digest([expenses['snapshot_digest'],revenue['snapshot_digest']]))
    report['report_digest']=digest(report)
    return report


def demo_revenue_accrual():
    from tempfile import TemporaryDirectory
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='accounting-revenue-accrual-') as directory:
        workspace=Workspace(directory)
        common=dict(schema_version=2,synthetic=True,entity_id=workspace.catalog.entity_id,currency='USD',
            event_id='service-january',counterparty_id='fictional-service-customer',counterparty='Fictional Service Customer',amount='250.00')
        completion=dict(common,document_id='service-completion',kind='service_completion',document_date='2026-01-28',
            completion_date='2026-01-28',description='Synthetic service completed January 28')
        basis=dict(common,document_id='service-cutoff',kind='revenue_accrual_basis',document_date='2026-01-31',
            cutoff_date='2026-01-31',status='unbilled_uncollected',description='Operator-supported whole revenue remains unbilled and uncollected at cutoff')
        for document in (completion,basis):workspace.action('operation-sources',dict(document=document))
        request=dict(completion_source_id=completion['document_id'],basis_source_id=basis['document_id'],expected_revision=0)
        draft=workspace.action('revenue-accrual-proposals',request)
        assert workspace.state()['journal_count']==0
        print('Pending revenue accrual: 250.00 USD; posted journals: 0; separate human confirmation required.')
        confirmation=dict(draft_id=draft['draft_id'],revision=draft['revision'],confirmed_digest=draft['content_digest'])
        posted=workspace.action('approve-post',confirmation)
        state=workspace.state();report=state['revenue_accruals']
        assert report['principal_cents']==report['control_cents']==25000 and report['unassigned_control_cents']==0
        with workspace.storage() as (_,ledger,_,_,_):
            lines=ledger.snapshot.entries[0].lines
            assert [(l.account,l.side,l.amount.cents) for l in lines]==[('1150','debit',25000),('4000','credit',25000)]
        print('Accrued Service Revenue debit 250.00; Service Revenue credit 250.00; Cash/AR unchanged.')
        print('Outstanding unbilled assets: 250.00; 1150 control: 250.00; residual: 0.00.')
        invoice=dict(common,document_id='later-invoice',kind='customer_invoice',document_date='2026-01-28',due_date='2026-01-31',
            invoice_number='LATER-001',description='Synthetic later customer invoice for the same completion event')
        workspace.action('operation-sources',dict(document=invoice))
        try:workspace.action('invoice-proposals',dict(invoice_source_id=invoice['document_id'],completion_source_id=completion['document_id']))
        except ValueError as error:
            assert 'duplicate economic event' in str(error)
            print('Duplicate invoice recognition refused:',error)
        else:raise AssertionError('duplicate invoice recognized the revenue twice')
        workspace=Workspace(directory)
        assert workspace.action('approve-post',confirmation)==posted
        assert workspace.action('revenue-accrual-proposals',request)==draft
        assert workspace.state()['journal_count']==1
        print('Restart and exact retries retain one immutable asset and journal.')
        print('Report:',report['report_policy'],report['snapshot_digest'])
