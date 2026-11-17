import type { UsageRecord } from '../contracts';
import { microUsd } from '../format';
import { percent, sumBy } from '../numbers';
import { navigateTo, plural, sortInsights, type Insight } from './types';

/** Recommendations from the loaded usage window; reader copy avoids administrator-only steps. */
export function usageInsights(records: UsageRecord[], admin: boolean): Insight[] {
  if (!records.length) return [];
  const insights: Insight[] = [];
  const unknown = records.filter((record) => record.status === 'usage_unknown');
  if (unknown.length) {
    const estimated = unknown.filter((record) => record.cost_micro_usd !== null);
    const charged = estimated.length
      ? `${plural(estimated.length, 'request')} ${estimated.length === 1 ? 'was' : 'were'} charged an estimated upper bound (${microUsd(sumBy(estimated, (record) => record.cost_micro_usd ?? 0))}) so budgets still decrement.`
      : 'They were not charged as zero.';
    insights.push({
      id: 'unknown-usage',
      severity: 'warning',
      title: `${plural(unknown.length, 'request')} finished without provider usage (${percent(unknown.length / records.length)}% of recent requests)`,
      detail: `${charged.trim()} Most recent: request ${unknown[0].request_id} (${unknown[0].model}, team ${unknown[0].team_id}, application ${unknown[0].subscription_id}). Ask that application's owner why no usage was reported.`,
      action: admin ? navigateTo('Open Azure dashboard', 'dashboard') : undefined,
    });
  }
  const outOfBounds = records.filter((record) => record.out_of_bounds);
  if (outOfBounds.length)
    insights.push({
      id: 'out-of-bounds',
      severity: 'warning',
      title: `${plural(outOfBounds.length, 'request')} exceeded the model token limits`,
      detail:
        'Providers reported more tokens than the limits pinned for the model. They are still priced as reported. Confirm the registered limits match the deployment.',
      action: admin ? navigateTo('Review model limits', 'models') : undefined,
    });
  return sortInsights(insights);
}
