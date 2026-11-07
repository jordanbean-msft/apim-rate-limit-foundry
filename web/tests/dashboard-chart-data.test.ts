import { describe, expect, it } from 'vitest';
import type { DashboardTile } from '../src/contracts';
import {
  buildDashboardChartModel,
  colorForDashboardLabel,
  formatDashboardValue,
} from '../src/components/dashboardChartData';

const tile: DashboardTile = {
  id: 'requests',
  title: 'Requests',
  chart: 'StackedColumn',
  x_axis: 'Timestamp',
  y_axis: 'Tokens',
  split_by: 'Model',
  columns: [
    { name: 'Timestamp', type: 'datetime' },
    { name: 'Model', type: 'string' },
    { name: 'Tokens', type: 'long' },
  ],
  rows: [
    ['2026-02-01T02:00:00Z', 'zeta', 2],
    ['2026-02-01T01:00:00Z', 'alpha', 3],
    ['2026-02-01T02:00:00Z', 'zeta', 4],
    ['2026-02-01T02:00:00Z', 'alpha', null],
  ],
  error: null,
  truncated: false,
};

describe('dashboard chart transformations', () => {
  it('sorts datetime categories and aggregates repeated values by split series', () => {
    const model = buildDashboardChartModel(tile);
    expect(model.dateAxis).toBe(true);
    expect(model.categories).toEqual(['2026-02-01T01:00:00Z', '2026-02-01T02:00:00Z']);
    expect(model.series.map(({ name }) => name)).toEqual(['alpha', 'zeta']);
    expect([...model.series[1].values]).toEqual([['2026-02-01T02:00:00Z', 6]]);
    expect(model.series[0].values.has('2026-02-01T02:00:00Z')).toBe(false);
  });

  it('aggregates pie categories and preserves labels and non-date category order', () => {
    const model = buildDashboardChartModel({
      ...tile,
      chart: 'Pie',
      x_axis: 'Model',
      y_axis: 'Tokens',
      split_by: null,
      rows: [
        ['zeta', 3],
        ['alpha', 2],
        ['zeta', 4],
      ],
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'Tokens', type: 'long' },
      ],
    });
    expect(model.categories).toEqual(['zeta', 'alpha']);
    expect(model.pie.map(({ legend, data }) => [legend, data])).toEqual([
      ['zeta', 7],
      ['alpha', 2],
    ]);
    expect(model.dateAxis).toBe(false);
  });

  it('formats currency, micro-USD and millisecond axes without changing source values', () => {
    expect(formatDashboardValue(1250, 'Cost (USD)')).toBe('$1.25K');
    expect(formatDashboardValue(0.000123, 'EffectiveUSD')).toBe('$0.000123');
    expect(formatDashboardValue(5, 'ReservedUSD')).toBe('$5');
    expect(formatDashboardValue(1_250_000, 'Cost in microUSD')).toBe('1.25 USD');
    expect(formatDashboardValue(1250, 'Latency (ms)')).toBe('1.25K ms');
  });

  it('assigns deterministic colors independent of row/category order', () => {
    expect(colorForDashboardLabel('Allowed')).toBe(colorForDashboardLabel('Allowed'));
    const first = buildDashboardChartModel({
      ...tile,
      chart: 'Pie',
      x_axis: 'Model',
      y_axis: 'Tokens',
      split_by: null,
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'Tokens', type: 'long' },
      ],
      rows: [
        ['Allowed', 3],
        ['Denied', 1],
      ],
    });
    const second = buildDashboardChartModel({
      ...tile,
      chart: 'Pie',
      x_axis: 'Model',
      y_axis: 'Tokens',
      split_by: null,
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'Tokens', type: 'long' },
      ],
      rows: [
        ['Denied', 1],
        ['Allowed', 3],
      ],
    });
    expect(first.pie.find((point) => point.legend === 'Allowed')?.color).toBe(
      second.pie.find((point) => point.legend === 'Allowed')?.color,
    );
  });

  it('returns no chart data when the axis columns are missing', () => {
    expect(buildDashboardChartModel({ ...tile, x_axis: 'missing' })).toMatchObject({
      categories: [],
      series: [],
      pie: [],
    });
  });
});
