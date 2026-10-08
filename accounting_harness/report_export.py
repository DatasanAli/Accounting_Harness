"""Deterministic, unsigned portable reports. Read-back never opens a ledger.

JSON is authoritative. CSV is a projection with report.json as its manifest;
text beginning with an apostrophe or = + - @ TAB CR LF is prefixed with one
apostrophe, reversibly. Encoded CSV cells are limited to 131072 characters;
JSON retains its independent member byte limit. Numeric cents/amount columns
are canonical decimal text.
Hashes verify internal consistency, not provenance, evidence or permission.
"""
import csv
import io
import json
import re
import zipfile
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from accounting_harness.cash_flow import CashFlowCapture, CashFlowPolicy, cash_flow_statement, _payable_trace
from accounting_harness.domain.accounts import Account, AccountCatalog, _unique_object, _validate_text
from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.journal import validate_journal
from accounting_harness.domain.ledger import LedgerEntry, LedgerLine, LedgerSnapshot
from accounting_harness.domain.money import Money
from accounting_harness.financial_reports import FinancialCapture, FinancialPolicy, JournalContext, financial_statements
from accounting_harness.persistence import _canonical
from accounting_harness.review import digest

SCHEMA = 'accounting-harness-portable-reports'
SCHEMA_VERSION = 1
CSV_POLICY = 'statement-rows-apostrophe-text-v1'
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 4 * 1024 * 1024
# Match the standard CSV parser ceiling without mutating its process-global limit.
MAX_CSV_FIELD_CHARS = 128 * 1024
CSV_HEADER = ('report','section','row_id','label','account','journal_id','effective_date',
              'cents','amount','currency','entity_id','period_start','period_end','as_of',
              'snapshot_digest','report_digest','package_digest','manifest')


def _bytes(value):
    return _canonical(value).encode('utf-8')


def _fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('unsupported or missing portable report fields')


def _list(value):
    if type(value) is not list:
        raise ValueError('portable report requires a JSON array')
    return value


def _integer(value):
    if type(value) is not str or not re.fullmatch(r'0|-?[1-9][0-9]*', value):
        raise ValueError('cents must be canonical decimal-integer strings')
    return int(value)


def _timestamp(value):
    _validate_text(value, 'recorded timestamp')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.isoformat() != value:
        raise ValueError('recorded timestamp must be canonical and timezone-aware')


def _json(raw):
    def refuse_number(_):
        raise ValueError('floating point and nonfinite JSON numbers are unsupported')
    return json.loads(raw, object_pairs_hook=_unique_object, parse_float=refuse_number,
                      parse_constant=refuse_number)


def _catalog(rows, entity, currency):
    accounts = []
    for row in _list(rows):
        _fields(row, 'code name classification normal_side active temporary')
        accounts.append(Account(**row))
    return AccountCatalog(entity, currency, tuple(accounts))


def _financial(data, cutoff):
    _fields(data, 'entity_id currency period_start period_end catalog policy entries')
    if _bytes(data['policy']) != _bytes(asdict(FinancialPolicy())):
        raise ValueError('unsupported financial report policy')
    catalog = _catalog(data['catalog'], data['entity_id'], data['currency'])
    start, end = accounting_date(data['period_start']), accounting_date(data['period_end'])
    # An inactive account may have valid historical lines. Validate its identity
    # and money using the existing admission rules without reactivating any book.
    historical_catalog = replace(catalog, accounts=tuple(replace(a, active=True) for a in catalog.accounts))
    entries, contexts, ids = [], [], set()
    for row in _list(data['entries']):
        _fields(row, 'journal_id entity_id currency effective_date description source_ids context lines')
        context = row['context']
        _fields(context, 'journal_id classification actor_id recorded_at original_entry_id')
        _validate_text(context['actor_id'], 'journal actor')
        _timestamp(context['recorded_at'])
        if context['journal_id'] != row['journal_id'] or row['journal_id'] in ids:
            raise ValueError('duplicate or inconsistent journal identity')
        ids.add(row['journal_id'])
        sources = _list(row['source_ids'])
        if len(set(sources)) != len(sources):
            raise ValueError('duplicate source reference')
        lines = []
        for line in _list(row['lines']):
            _fields(line, 'account side cents amount')
            cents = _integer(line['cents'])
            if cents <= 0 or str(Money(cents)) != line['amount']:
                raise ValueError('journal cents and decimal amount disagree')
            lines.append(LedgerLine(line['account'], line['side'], Money(cents)))
        proposal = dict(id=row['journal_id'],entity_id=row['entity_id'],currency=row['currency'],
            effective_date=row['effective_date'],description=row['description'],source_ids=sources,
            lines=[dict(account=l.account,side=l.side,amount=l.amount) for l in lines])
        validation = validate_journal(proposal, historical_catalog, known_source_ids=set(sources))
        day = accounting_date(row['effective_date'])
        if not validation.accepted or not start <= day <= end:
            raise ValueError('invalid captured journal, date, balance or reference')
        entries.append(LedgerEntry(row['journal_id'],row['entity_id'],row['currency'],day,
                                   row['description'],tuple(sources),tuple(lines)))
        contexts.append(JournalContext(**context))
    by_id = {entry.id:entry for entry in entries}
    for context in contexts:
        original = context.original_entry_id
        if original is not None:
            _validate_text(original, 'original journal')
            if original not in by_id or original == context.journal_id:
                raise ValueError('missing or self-referencing original journal')
            entry, basis = by_id[context.journal_id], by_id[original]
            signed = lambda e: sorted((l.account,l.amount.cents*(1 if l.side=='debit' else -1)) for l in e.lines)
            if entry.effective_date < basis.effective_date or signed(entry) != sorted((a,-c) for a,c in signed(basis)):
                raise ValueError('reversal does not reverse its captured original journal')
    return FinancialCapture(LedgerSnapshot(catalog,start,end,tuple(entries)),accounting_date(cutoff),
                            tuple(contexts),FinancialPolicy())


def _trace(trace, financial):
    _fields(trace, 'bills payments approvals')
    schemas = {
        'bills':'bill_id vendor_id bill_number recognition_event_id bill_source_id incurrence_source_id principal_cents expense_account effective_date due_date approval_id journal_id',
        'payments':'payment_event_id bill_id cash_source_id allocated_cents effective_date approval_id journal_id',
        'approvals':'approval_id draft_id revision binding_json actor_id recorded_at policy_version journal_id',
    }
    identities = {'bills':'bill_id','payments':'payment_event_id','approvals':'approval_id'}
    entries = {e.id:e for e in financial.ledger.entries}
    maps = {}
    for kind, schema in schemas.items():
        maps[kind] = {}
        for row in _list(trace[kind]):
            _fields(row, schema)
            for key, value in row.items():
                if key == 'revision':
                    if type(value) is not int or value <= 0:
                        raise ValueError('approval revision must be a positive integer')
                else:
                    _validate_text(value, key)
                    if key.endswith('_cents') and _integer(value) <= 0:
                        raise ValueError('payable amounts must be positive')
                    if key.endswith('_date'): accounting_date(value)
                    if key == 'recorded_at': _timestamp(value)
            identity = row[identities[kind]]
            if identity in maps[kind] or row['journal_id'] not in entries:
                raise ValueError('duplicate or missing payable journal reference')
            maps[kind][identity] = row
    for approval in trace['approvals']:
        if digest([approval['binding_json'],approval['actor_id']]) != approval['approval_id']:
            raise ValueError('captured approval content identity mismatch')
        binding = _json(approval['binding_json'])
        _fields(binding, 'action draft_id entity_id evidence ledger_context policy_version revision revision_digest')
        if (binding['action'] != 'post' or binding['entity_id'] != financial.ledger.catalog.entity_id
            or binding['draft_id'] != approval['draft_id'] or type(binding['revision']) is not int
            or binding['revision'] != approval['revision'] or binding['policy_version'] != approval['policy_version']):
            raise ValueError('inconsistent captured approval binding')
        if not re.fullmatch('[0-9a-f]{64}',binding['revision_digest']):
            raise ValueError('invalid captured revision digest')
        if type(binding['evidence']) is not dict or not binding['evidence']:
            raise ValueError('captured approval evidence references required')
        for source, fingerprint in binding['evidence'].items():
            _validate_text(source, 'evidence reference')
            if type(fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}',fingerprint):
                raise ValueError('invalid evidence digest')
        context = _json(binding['ledger_context'])
        _fields(context, 'catalog known_source_ids period_start period_end report_policy')
        _fields(context['catalog'], 'accounts currency entity_id')
        _catalog(context['catalog']['accounts'], context['catalog']['entity_id'], context['catalog']['currency'])
        if (context['catalog']['entity_id'] != financial.ledger.catalog.entity_id
            or context['catalog']['currency'] != financial.ledger.catalog.currency
            or context['period_start'] != financial.ledger.period_start.isoformat()
            or context['period_end'] != financial.ledger.period_end.isoformat()
            or context['report_policy'] != 'unadjusted-zero-opening-v1'):
            raise ValueError('unsupported captured approval ledger context')
        for source in _list(context['known_source_ids']): _validate_text(source, 'historical source reference')
    used_approvals = set()
    for kind in ('bills','payments'):
        for fact in trace[kind]:
            approval = maps['approvals'].get(fact['approval_id'])
            if approval is None or approval['journal_id'] != fact['journal_id'] or fact['approval_id'] in used_approvals:
                raise ValueError('missing or reused payable approval reference')
            used_approvals.add(fact['approval_id'])
            entry = entries[fact['journal_id']]
            binding = _json(approval['binding_json'])
            if entry.effective_date.isoformat() != fact['effective_date'] or set(binding['evidence']) != set(entry.source_ids):
                raise ValueError('payable date or source references disagree with journal')
            if kind == 'bills':
                expected = sorted([(fact['expense_account'],'debit',int(fact['principal_cents'])),('2000','credit',int(fact['principal_cents']))])
                if (approval['policy_version'] != 'bill-v1' or fact['expense_account'] not in ('5000','5100')
                    or fact['due_date'] < fact['effective_date']
                    or sorted(entry.source_ids) != sorted([fact['bill_source_id'],fact['incurrence_source_id']])
                    or sorted((l.account,l.side,l.amount.cents) for l in entry.lines) != expected):
                    raise ValueError('captured bill facts disagree with approved journal')
            elif fact['bill_id'] not in maps['bills'] or not _payable_trace(entry,trace,entries,CashFlowPolicy()):
                raise ValueError('captured payment facts disagree with approved journals')
    if used_approvals != set(maps['approvals']):
        raise ValueError('unreferenced payable approval')


def report_package(capture):
    """Render every linked report from the single immutable supplied capture."""
    statements = financial_statements(capture.financial)
    cash = cash_flow_statement(capture)
    package = dict(schema=SCHEMA,schema_version=SCHEMA_VERSION,csv_policy=CSV_POLICY,
        as_of=capture.financial.as_of.isoformat(),capture=cash['capture'],
        reports=dict(financial_statements=statements,cash_flow=cash))
    package['package_digest'] = digest(package)
    # JSON-normalize policy tuples without changing historical report identities.
    return json.loads(_canonical(package))


def csv_text_encode(value):
    return "'" + value if value.startswith(("'",'=', '+', '-', '@', '\t', '\r', '\n')) else value


def csv_text_decode(value):
    return value[1:] if value.startswith("'") else value


def _csv_fields(values):
    if any(len(value) > MAX_CSV_FIELD_CHARS for value in values):
        raise ValueError(f'CSV field exceeds {MAX_CSV_FIELD_CHARS} characters after text encoding')
    return values


def _csv_rows(raw):
    return [_csv_fields(row) for row in csv.reader(io.StringIO(raw.decode('utf-8'),newline=''),strict=True)]


def _csv(package):
    output = io.StringIO(newline='')
    writer = csv.writer(output,lineterminator='\r\n');writer.writerow(CSV_HEADER)
    statements = package['reports']['financial_statements']
    reports = [statements[k] for k in ('income_statement','owners_equity','balance_sheet')]
    reports.append(package['reports']['cash_flow'])
    for report in reports:
        def row(section,identity,label,cents,amount,account='',journal='',day=''):
            values = [report['statement'],section,identity,label,account,journal,day,cents,amount,
                report['currency'],report['entity_id'],report['period_start'],report['period_end'],report['as_of'],
                report['snapshot_digest'],report['report_digest'],package['package_digest'],'report.json']
            writer.writerow(_csv_fields([v if i in (7,8) else csv_text_encode(v) for i,v in enumerate(values)]))
        for section in ('revenue','expenses','contributions','drawings','assets','liabilities'):
            selected = report.get(section, [])
            if isinstance(selected,dict): selected = [selected]
            for account in selected:
                row(section,account['account'],account['name'],account['net_cents'],account['amount'],account['account'])
                for detail in account['drilldown']:
                    row(section+'_journal',detail['journal_id']+':'+str(detail['line_number']),detail['description'],
                        detail['net_cents'],detail['amount'],account['account'],detail['journal_id'],detail['effective_date'])
        for detail in report.get('rows',[]):
            row(detail['category'],detail['journal_id'],detail['description'],detail['cash_cents'],detail['cash_amount'],
                journal=detail['journal_id'],day=detail['effective_date'])
        for key in sorted(report):
            if key.endswith('_cents'):
                name = key.removesuffix('_cents')
                row('totals',name,name.replace('_',' '),report[key],report[name+'_amount'])
    return output.getvalue().encode('utf-8')


def export_report_package(package, kind='json'):
    """Deterministic JSON, or fixed-name CSV plus the same JSON manifest."""
    if kind not in ('json','zip'):
        raise ValueError('report format must be json or zip')
    manifest = _bytes(package)
    if len(manifest) > MAX_MEMBER_BYTES:
        raise ValueError('report manifest exceeds synthetic package size limit')
    if kind == 'json': return manifest
    projection = _csv(package)
    if len(projection) > MAX_MEMBER_BYTES:
        raise ValueError('CSV exceeds synthetic package size limit')
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED) as archive:
        for name, data in [('report.json',manifest),('report.csv',projection)]:
            info = zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.create_system = 3; info.external_attr = 0o100644 << 16
            archive.writestr(info,data)
    result = output.getvalue()
    if len(result) > MAX_PACKAGE_BYTES:
        raise ValueError('report archive exceeds synthetic package size limit')
    return result


def read_report_package(raw):
    """Bounded offline integrity verification; result has no posting authority."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_PACKAGE_BYTES:
        raise ValueError('report package must be bounded nonempty bytes')
    try:
        projection = None
        if raw.startswith(b'PK'):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = archive.infolist()
                if len(members) != 2 or [m.filename for m in members] != ['report.json','report.csv']:
                    raise ValueError('archive must contain only report.json then report.csv')
                for member in members:
                    if (not 0 < member.file_size <= MAX_MEMBER_BYTES or member.flag_bits & 1
                        or member.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                        or (member.external_attr >> 16) & 0o170000 not in (0,0o100000)):
                        raise ValueError('unsafe or oversized report archive member')
                # No extraction. Bound actual reads as well as declared sizes.
                content = []
                for member in members:
                    with archive.open(member) as stream: data = stream.read(MAX_MEMBER_BYTES+1)
                    if len(data) > MAX_MEMBER_BYTES:
                        raise ValueError('oversized report archive content')
                    content.append(data)
                manifest, projection = content
        else:
            manifest = raw
        if len(manifest) > MAX_MEMBER_BYTES:
            raise ValueError('oversized JSON report manifest')
        package = _json(manifest.decode('utf-8'))
        _fields(package, 'schema schema_version csv_policy as_of capture reports package_digest')
        if (package['schema'] != SCHEMA or type(package['schema_version']) is not int
            or package['schema_version'] != SCHEMA_VERSION or package['csv_policy'] != CSV_POLICY):
            raise ValueError('unsupported portable report schema or projection policy')
        captured = package['capture']
        _fields(captured, 'kind schema_version financial payables policy')
        if (captured['kind'] != 'direct_cash_flow' or type(captured['schema_version']) is not int
            or captured['schema_version'] != 1 or _bytes(captured['policy']) != _bytes(asdict(CashFlowPolicy()))):
            raise ValueError('unsupported cash-flow capture or policy')
        financial = _financial(captured['financial'],package['as_of'])
        if CashFlowPolicy().cash_account not in {a.code for a in financial.ledger.catalog.accounts}:
            raise ValueError('captured cash account reference is missing')
        _trace(captured['payables'],financial)
        capture = CashFlowCapture(financial,_canonical(captured['payables']))
        expected = report_package(capture)
        if _bytes(package) != _bytes(expected):
            raise ValueError('report capture, calculated values or digests disagree')
        if projection is not None:
            actual_rows = _csv_rows(projection)
            expected_rows = _csv_rows(_csv(expected))
            if actual_rows != expected_rows:
                raise ValueError('CSV projection disagrees with its report manifest')
        return expected
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,UnicodeError,
            csv.Error,zipfile.BadZipFile,NotImplementedError,RuntimeError) as error:
        raise ValueError('invalid portable report package: '+str(error)) from error


def report_preview(package):
    reports = package['reports']; statements = reports['financial_statements']; cash = reports['cash_flow']
    return dict(label='Imported report · untrusted, read-only',posting_authority=False,
        integrity='Internal consistency only; unsigned data does not establish provenance or authorization.',
        entity_id=statements['entity_id'],period_start=statements['period_start'],period_end=statements['period_end'],
        as_of=package['as_of'],package_digest=package['package_digest'],snapshot_digest=cash['snapshot_digest'],
        financial_snapshot_digest=statements['snapshot_digest'],
        report_digests={k:reports[k]['report_digest'] for k in reports},
        ending_cash=cash['ending_cash_amount'],net_income=statements['income_statement']['net_income_amount'],
        ending_equity=statements['owners_equity']['ending_equity_amount'])


def verify_report_file(path):
    # CLI path only. No web handler accepts or opens a caller-supplied path.
    with Path(path).open('rb') as stream: raw = stream.read(MAX_PACKAGE_BYTES+1)
    preview = report_preview(read_report_package(raw))
    print(json.dumps(preview,ensure_ascii=False,indent=2))
    return preview


def demo_report_export():
    from tempfile import TemporaryDirectory
    from accounting_harness.adjusted_month import build_adjusted_month
    from accounting_harness.workspace import Workspace
    with TemporaryDirectory(prefix='report-export-demo-') as directory:
        workspace = Workspace(directory);build_adjusted_month(workspace)
        package = workspace.report_package('2026-01-31')
        before = workspace.state()
        for kind in ('json','zip'):
            raw = export_report_package(package,kind)
            assert read_report_package(raw) == package
            assert export_report_package(package,kind) == raw
            path = Path(directory)/('report.'+kind);path.write_bytes(raw)
            preview = verify_report_file(path)
        assert workspace.state() == before
        assert (preview['ending_cash'],preview['net_income'],preview['ending_equity']) == ('9400.00','1100.00','10900.00')
        print('Snapshot:',preview['snapshot_digest'])
        print('Package:',preview['package_digest'])
        print('Cash: 9400.00; income: 1100.00; equity: 10900.00; exact offline JSON/CSV round-trip')
