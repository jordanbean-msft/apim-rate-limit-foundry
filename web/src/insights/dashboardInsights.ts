import type { DashboardPeriod, DashboardTile } from '../contracts';
import { customStep, plural, sortInsights, type Insight } from './types';

/** Tile-level health: failed queries, empty results and truncation each have a concrete fix. */
export function dashboardInsights(tiles: DashboardTile[], period: DashboardPeriod): Insight[] {
  const insights: Insight[] = [];
  const failed = tiles.filter((tile) => tile.error);
  if (failed.length)
    insights.push({
      id: 'failed-tiles',
      severity: 'warning',
      title: `${plural(failed.length, 'tile')} could not load`,
      detail: `${failed[0].title}: ${failed[0].error}${failed.length > 1 ? ` (and ${failed.length - 1} more)` : ''}`,
      action: customStep('Retry tiles', 'retry'),
    });
  const empty = tiles.filter((tile) => !tile.error && !tile.rows.length);
  if (tiles.length && empty.length === tiles.length)
    insights.push({
      id: 'no-telemetry',
      severity: 'warning',
      title: `All ${plural(tiles.length, 'tile')} returned no rows for this time range`,
      detail: 'There is nothing to chart for the selected range.',
      action: period === '7d' ? undefined : customStep('Show last 7 days', 'wider-range'),
    });
  const truncated = tiles.filter((tile) => tile.truncated);
  if (truncated.length && period !== '1h')
    insights.push({
      id: 'truncated-tiles',
      severity: 'info',
      title: `${plural(truncated.length, 'tile')} limited to 1,000 results`,
      detail: 'The charts omit older rows. Shorten the time range to see every data point.',
      action: customStep('Show last hour', 'shorter-range'),
    });
  return sortInsights(insights);
}
