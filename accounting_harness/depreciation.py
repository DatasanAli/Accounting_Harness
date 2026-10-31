"""Supplied-input projections only; no asset enrollment or financial writes."""
import calendar
from datetime import date

from accounting_harness.domain.dates import accounting_date
from accounting_harness.domain.money import Money
from accounting_harness.persistence import MAX_CENTS
from accounting_harness.review import digest

POLICY = 'straight-line-full-month-final-remainder-v1'


def depreciation_schedule(*, entity_id, asset_id, cost, residual, months, in_service,
                          currency='USD', policy=POLICY):
    """Allocate integer cents from the in-service month, remainder in final month.

    IDs and assumptions are supplied labels, not authenticated or enrolled facts.
    Recomputing returns a new projection and never approves or posts an entry.
    """
    if policy != POLICY:
        raise ValueError('unsupported depreciation policy')
    for label, value in (('entity_id', entity_id), ('asset_id', asset_id)):
        if (type(value) is not str or not value or value != value.strip()
                or len(value) > 200 or not value.isprintable()):
            raise ValueError(label + ' must be trimmed printable text of 1 through 200 characters')
    amounts = []
    for label, value in (('cost', cost), ('residual', residual)):
        if type(value) is not str or len(value) > 64:
            raise ValueError(label + ' must be a decimal string of at most 64 characters')
        amount = Money.parse(value, currency)
        if amount.cents > MAX_CENTS:
            raise ValueError(label + ' exceeds the supported integer-cent limit')
        amounts.append(amount)
    cost_money, residual_money = amounts
    if cost_money.cents == 0 or residual_money.cents > cost_money.cents:
        raise ValueError('cost must be positive and residual must not exceed cost')
    if type(months) is not int or not 1 <= months <= 1200:
        raise ValueError('useful life must be an integer from 1 through 1200 months')
    start = accounting_date(in_service)
    first_month = (start.year - 1) * 12 + start.month - 1
    if first_month + months > 9999 * 12:
        raise ValueError('schedule extends beyond December 9999')
    inputs = dict(entity_id=entity_id, asset_id=asset_id, currency=currency,
                  cost=str(cost_money), residual=str(residual_money), months=months,
                  in_service=start.isoformat())
    report = dict(schema_version=1, policy=policy, basis='supplied_inputs_projection', inputs=inputs)
    report['schedule_digest'] = digest(report)
    depreciable = cost_money.cents - residual_money.cents
    monthly, remainder = divmod(depreciable, months)
    accumulated, rows = 0, []
    for offset in range(months):
        year, month = divmod(first_month + offset, 12)
        year, month = year + 1, month + 1
        end = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
        amount = monthly + (remainder if offset == months - 1 else 0)
        accumulated += amount
        rows.append(dict(month=end[:7], effective_date=end, depreciation=str(Money(amount)),
                         accumulated_depreciation=str(Money(accumulated)),
                         carrying_value=str(Money(cost_money.cents - accumulated))))
    return dict(report, rows=rows, total_depreciation=str(Money(accumulated)),
                ending_carrying_value=str(Money(cost_money.cents - accumulated)))


def demo_depreciation():
    inputs = dict(entity_id='demo-service-001', asset_id='synthetic-laptop',
                  cost='1200.00', residual='0.00', months=12, in_service='2026-01-15')
    report = depreciation_schedule(**inputs)
    assert [row['depreciation'] for row in report['rows']] == ['100.00'] * 12
    assert report['total_depreciation'] == '1200.00' and report['ending_carrying_value'] == '0.00'
    assert depreciation_schedule(**inputs) == report
    print('Supplied-input projection; no asset enrollment, approval or journal posting.')
    print('Policy:', report['policy'])
    print('Asset 1200.00 USD, residual 0.00, 12 full months from 2026-01-15:')
    for row in report['rows']:
        print(row['effective_date'], 'depreciation', row['depreciation'],
              'accumulated', row['accumulated_depreciation'], 'carrying value', row['carrying_value'])
    rounded = depreciation_schedule(**dict(inputs, cost='100.00', residual='10.00',
                                          months=7, in_service='2027-11-30'))
    assert [r['depreciation'] for r in rounded['rows']] == ['12.85'] * 6 + ['12.90']
    assert rounded['rows'][3]['effective_date'] == '2028-02-29'
    assert rounded['ending_carrying_value'] == '10.00'
    print('Remainder example: six months at 12.85, final month 12.90; residual 10.00.')
    try:
        depreciation_schedule(**dict(inputs, residual='1200.01'))
    except ValueError:
        print('Rejected residual above cost. Repeated calculation is identical; no records written.')
    else:
        raise AssertionError('invalid residual accepted')
