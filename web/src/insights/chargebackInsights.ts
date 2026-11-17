import type { ChargebackRow } from '../contracts';
import { microUsd } from '../format';
import { sumBy } from '../numbers';
import { navigateTo, plural, sortInsights, type Insight } from './types';

/** Month-end and allocation checks that decide whether a chargeback export is safe to use. */
export function chargebackInsights(
  rows: ChargebackRow[],
  month: string,
  now: Date,
  admin: boolean,
): Insight[] {
  const insights: Insight[] = [];
  const currentMonth = now.toISOString().slice(0, 7);
  if (month === currentMonth) {
    const [year, monthNumber] = month.split('-').map(Number);
    const daysLeft = Math.max(
      0,
      Math.ceil((Date.UTC(year, monthNumber, 1) - now.getTime()) / 86_400_000),
    );
    insights.push({
      id: 'open-month',
      severity: 'info',
      title: `${month} is still open`,
      detail: `Totals are provisional for ${plural(daysLeft, 'more day')}; spend recorded after this point will change them.`,
    });
  }
  if (!rows.length) return sortInsights(insights);
  const unknown = sumBy(rows, (row) => row.unknown_requests);
  if (unknown)
    insights.push({
      id: 'unknown-requests',
      severity: 'warning',
      title: `${plural(unknown, 'request')} have no reported usage`,
      detail:
        'These requests are counted separately, so actual spend may be understated. Review them before allocating costs to departments.',
      action: navigateTo('Review usage records', 'usage'),
    });
  const estimated = rows.filter((row) => row.cost_basis === 'estimated_upper_bound');
  if (estimated.length)
    insights.push({
      id: 'estimated-cost',
      severity: 'info',
      title: `${plural(estimated.length, 'row')} use an estimated upper-bound cost`,
      detail: `${microUsd(sumBy(estimated, (row) => row.cost_micro_usd ?? 0))} of the total is an estimate. Reconcile with the provider invoice before final chargeback.`,
    });
  const unallocated = rows.filter((row) => !row.business_unit.trim() || !row.cost_center.trim());
  if (unallocated.length)
    insights.push({
      id: 'missing-cost-center',
      severity: 'warning',
      title: `${plural(unallocated.length, 'row')} missing a business unit or cost center`,
      detail:
        'These costs cannot be charged back. Fill in the organization unit so they allocate correctly.',
      action: admin ? navigateTo('Fix organization units', 'organizations') : undefined,
    });
  return sortInsights(insights);
}
