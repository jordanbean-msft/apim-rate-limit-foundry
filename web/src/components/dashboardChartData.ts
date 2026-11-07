import type { DashboardScalar, DashboardTile } from '../contracts';

export const dashboardColors = [
  '#0078d4',
  '#8764b8',
  '#00a88f',
  '#d83b01',
  '#498205',
  '#ca5010',
  '#4f6bed',
  '#c239b3',
];

export function colorForDashboardLabel(label: string): string {
  let hash = 0;
  for (const character of label) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return dashboardColors[hash % dashboardColors.length];
}

export interface DashboardChartModel {
  categories: string[];
  series: { name: string; color: string; values: Map<string, number> }[];
  pie: { legend: string; data: number; color: string }[];
  dateAxis: boolean;
}

function scalarLabel(value: DashboardScalar): string {
  if (value === null) return '(empty)';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function finiteNumber(value: DashboardScalar): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function isDateValue(value: DashboardScalar, type: string): boolean {
  if (typeof value !== 'string') return false;
  return /date|time/i.test(type) || /^\d{4}-\d{2}-\d{2}T/.test(value);
}

export function buildDashboardChartModel(tile: DashboardTile): DashboardChartModel {
  const xIndex = tile.columns.findIndex((column) => column.name === tile.x_axis);
  const yIndex = tile.columns.findIndex((column) => column.name === tile.y_axis);
  const splitIndex = tile.split_by
    ? tile.columns.findIndex((column) => column.name === tile.split_by)
    : -1;
  if (xIndex < 0 || yIndex < 0 || (tile.split_by && splitIndex < 0)) {
    return { categories: [], series: [], pie: [], dateAxis: false };
  }

  const firstX = tile.rows.find((row) => row[xIndex] !== null)?.[xIndex] ?? null;
  const dateAxis = isDateValue(firstX, tile.columns[xIndex].type);
  const totals = new Map<string, Map<string, number>>();
  for (const row of tile.rows) {
    const rawX = row[xIndex];
    const value = finiteNumber(row[yIndex]);
    if (rawX === undefined || value === undefined) continue;
    const category = scalarLabel(rawX);
    const seriesName =
      splitIndex < 0 ? (tile.y_axis ?? 'Value') : scalarLabel(row[splitIndex] ?? null);
    const bySeries = totals.get(category) ?? new Map<string, number>();
    bySeries.set(seriesName, (bySeries.get(seriesName) ?? 0) + value);
    totals.set(category, bySeries);
  }

  const categories = [...totals.keys()];
  if (dateAxis) categories.sort((left, right) => Date.parse(left) - Date.parse(right));
  const seriesNames = [
    ...new Set([...totals.values()].flatMap((values) => [...values.keys()])),
  ].sort();
  const series = seriesNames.map((name) => ({
    name,
    color: colorForDashboardLabel(name),
    values: new Map(
      categories.flatMap((category) => {
        const value = totals.get(category)?.get(name);
        return value === undefined ? [] : [[category, value] as const];
      }),
    ),
  }));
  const pie = categories.flatMap((category) => {
    const value = [...(totals.get(category)?.values() ?? [])].reduce((sum, item) => sum + item, 0);
    return value > 0
      ? [{ legend: category, data: value, color: colorForDashboardLabel(category) }]
      : [];
  });
  return { categories, series, pie, dateAxis };
}

export function formatDashboardValue(value: number, axisTitle: string | null): string {
  const axis = axisTitle ?? '';
  const compact = new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value);
  if (/micro.?usd|usd.?micro/i.test(axis)) {
    return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value / 1_000_000)} USD`;
  }
  if (/USD|\$/i.test(axis)) {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: 'USD',
      notation: 'compact',
      minimumFractionDigits: 0,
      maximumFractionDigits: Math.abs(value) < 1 ? 6 : 2,
    }).format(value);
  }
  if (/\bms\b|millisecond/i.test(axis)) return `${compact} ms`;
  return compact;
}

export function dashboardDate(value: string | number | Date): Date | number {
  return value instanceof Date ? value : typeof value === 'number' ? value : new Date(value);
}
