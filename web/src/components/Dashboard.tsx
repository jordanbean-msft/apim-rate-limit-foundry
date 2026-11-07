import { useCallback, useEffect, useRef, useState } from 'react';
import {
  DonutChart,
  GroupedVerticalBarChart,
  LineChart,
  VerticalBarChart,
  VerticalStackedBarChart,
  type LineChartDataPoint,
  type VerticalStackedChartProps,
} from '@fluentui/react-charts';
import { Button, MessageBar, MessageBarBody, Select, Spinner } from '@fluentui/react-components';
import { ArrowClockwiseRegular } from '@fluentui/react-icons';
import type { DashboardChartModel } from './dashboardChartData';
import {
  buildDashboardChartModel,
  colorForDashboardLabel,
  dashboardDate,
  formatDashboardValue,
} from './dashboardChartData';
import type { DashboardPeriod, DashboardScalar, DashboardTile, PortalApi } from '../contracts';

const periods: { value: DashboardPeriod; label: string }[] = [
  { value: '1h', label: 'Last hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
];

export function Dashboard({ api, fixtureMode }: { api: PortalApi; fixtureMode: boolean }) {
  const [period, setPeriod] = useState<DashboardPeriod>('24h');
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === 'undefined' ? 1400 : window.innerWidth,
  );
  const [tiles, setTiles] = useState<DashboardTile[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const mounted = useRef(false);

  const refresh = useCallback(async () => {
    const requestId = ++sequence.current;
    setLoading(true);
    setError('');
    try {
      const result = await api.dashboard(period);
      if (requestId !== sequence.current || !mounted.current) return;
      setTiles(result);
      setHasLoaded(true);
    } catch (cause) {
      if (requestId !== sequence.current || !mounted.current) return;
      setError(cause instanceof Error ? cause.message : 'The Azure dashboard could not be loaded.');
      setTiles([]);
      setHasLoaded(true);
    } finally {
      if (requestId === sequence.current && mounted.current) setLoading(false);
    }
  }, [api, period]);

  useEffect(() => {
    const updateWidth = () => setViewportWidth(window.innerWidth);
    window.addEventListener('resize', updateWidth);
    return () => window.removeEventListener('resize', updateWidth);
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
    };
  }, [refresh]);

  const chartWidth = Math.max(300, Math.min(780, (viewportWidth - 340) / 2 - 36));

  return (
    <section className="dashboard-page" aria-label="Azure dashboard">
      <div className="dashboard-toolbar surface">
        <label>
          Time range
          <Select
            aria-label="Dashboard time range"
            value={period}
            onChange={(_, data) => setPeriod(data.value as DashboardPeriod)}
          >
            {periods.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
        </label>
        <Button icon={<ArrowClockwiseRegular />} disabled={loading} onClick={() => void refresh()}>
          Refresh dashboard
        </Button>
        {loading && (
          <div role="status">
            <Spinner size="tiny" label="Loading Azure dashboard tiles…" />
          </div>
        )}
      </div>
      {fixtureMode && (
        <p className="dashboard-fixture-label">
          Local fixture mode — these charts are illustrative fixtures, not live Azure dashboard
          data.
        </p>
      )}
      {error && (
        <div role="alert">
          <MessageBar intent="error">
            <MessageBarBody>
              <strong>Dashboard unavailable.</strong> {error} Retry with Refresh dashboard. No
              sample data has been substituted.
            </MessageBarBody>
          </MessageBar>
        </div>
      )}
      {hasLoaded && !error && !tiles.length && (
        <div className="surface empty-state">
          <h2>No dashboard tiles returned</h2>
          <p>The configured Azure dashboard did not return tiles for this time range.</p>
        </div>
      )}
      <div className="dashboard-grid">
        {tiles.map((tile) => (
          <DashboardTileView key={tile.id} tile={tile} chartWidth={chartWidth} />
        ))}
      </div>
    </section>
  );
}

function DashboardTileView({ tile, chartWidth }: { tile: DashboardTile; chartWidth: number }) {
  const model = buildDashboardChartModel(tile);
  const isTable = tile.chart === '';
  const chartLabel = `${tile.title}. ${tile.x_axis} by ${tile.y_axis}.`;
  return (
    <article className="surface dashboard-tile" aria-labelledby={`dashboard-title-${tile.id}`}>
      <header className="dashboard-tile-header">
        <div>
          <h2 id={`dashboard-title-${tile.id}`}>{tile.title}</h2>
          {!isTable && (
            <p>
              {tile.x_axis} · {tile.y_axis}
              {tile.split_by ? ` · split by ${tile.split_by}` : ''}
            </p>
          )}
        </div>
        {tile.truncated && (
          <span className="dashboard-truncated" role="status">
            Limited to 1,000 results
          </span>
        )}
      </header>
      {tile.error ? (
        <div className="dashboard-tile-state" role="alert">
          <strong>Tile unavailable.</strong> {tile.error}
        </div>
      ) : !tile.rows.length ? (
        <div className="dashboard-tile-state">No data for this time range.</div>
      ) : isTable ? (
        <DashboardTable tile={tile} />
      ) : (
        <div className="dashboard-chart" role="img" aria-label={chartLabel}>
          <Chart tile={tile} model={model} width={chartWidth} />
        </div>
      )}
      {!tile.error && tile.rows.length > 0 && !isTable && (
        <details className="dashboard-data-details">
          <summary>View data table ({tile.rows.length} rows)</summary>
          <DashboardTable tile={tile} />
        </details>
      )}
      {tile.truncated && (
        <p className="dashboard-truncated-note">
          This tile is limited to 1,000 results; choose a shorter time range to see more detail.
        </p>
      )}
    </article>
  );
}

function Chart({
  tile,
  model,
  width,
}: {
  tile: DashboardTile;
  model: DashboardChartModel;
  width: number;
}) {
  const yAxisTickFormat = (value: number) => formatDashboardValue(value, tile.y_axis);
  if (!model.categories.length || !model.series.length)
    return <p className="dashboard-tile-state">No plottable values for this tile.</p>;

  if (tile.chart === 'Pie') {
    return model.pie.length ? (
      <DonutChart
        data={{ chartTitle: tile.title, chartData: model.pie }}
        width={width}
        height={300}
        hideLabels={false}
        showLabelsInPercent
      />
    ) : (
      <p className="dashboard-tile-state">No plottable values for this tile.</p>
    );
  }

  if (tile.chart === 'StackedColumn') {
    const groups: VerticalStackedChartProps[] = model.categories.map((category) => ({
      xAxisPoint: model.dateAxis ? dashboardDate(category) : category,
      chartData: model.series.flatMap((series) => {
        const value = series.values.get(category);
        return value === undefined
          ? []
          : [
              {
                legend: series.name,
                data: value,
                color: series.color,
                yAxisCalloutData: formatDashboardValue(value, tile.y_axis),
              },
            ];
      }),
    }));
    return (
      <VerticalStackedBarChart
        data={groups}
        chartTitle={tile.title}
        width={width}
        height={330}
        yAxisTitle={tile.y_axis ?? undefined}
        xAxisTitle={tile.x_axis ?? undefined}
        yAxisTickFormat={yAxisTickFormat}
        hideLabels
      />
    );
  }

  if (tile.chart === 'Column' && tile.split_by) {
    const grouped = model.categories.map((category) => ({
      name: model.dateAxis
        ? new Date(category).toLocaleString(undefined, { timeZone: 'UTC' })
        : category,
      series: model.series.flatMap((series) => {
        const value = series.values.get(category);
        return value === undefined
          ? []
          : [
              {
                key: series.name,
                legend: series.name,
                data: value,
                color: series.color,
                xAxisCalloutData: category,
                yAxisCalloutData: formatDashboardValue(value, tile.y_axis),
              },
            ];
      }),
    }));
    return (
      <GroupedVerticalBarChart
        data={grouped}
        chartTitle={tile.title}
        width={width}
        height={330}
        colors={model.series.map((item) => item.color)}
        yAxisTitle={tile.y_axis ?? undefined}
        xAxisTitle={tile.x_axis ?? undefined}
        yAxisTickFormat={yAxisTickFormat}
        hideLabels
      />
    );
  }

  if (tile.chart === 'Column') {
    const bars = model.categories.map((category) => {
      const value = model.series.reduce(
        (sum, series) => sum + (series.values.get(category) ?? 0),
        0,
      );
      return {
        x: model.dateAxis ? dashboardDate(category) : category,
        y: value,
        color: colorForDashboardLabel(category),
        xAxisCalloutData: category,
        yAxisCalloutData: formatDashboardValue(value, tile.y_axis),
      };
    });
    return (
      <VerticalBarChart
        data={bars}
        chartTitle={tile.title}
        width={width}
        height={330}
        yAxisTitle={tile.y_axis ?? undefined}
        xAxisTitle={tile.x_axis ?? undefined}
        yAxisTickFormat={yAxisTickFormat}
        hideLabels
      />
    );
  }

  const categoryIndices = new Map(model.categories.map((category, index) => [category, index]));
  const lines = model.series.map((series) => ({
    legend: series.name,
    color: series.color,
    data: model.categories.flatMap((category): LineChartDataPoint[] => {
      const value = series.values.get(category);
      if (value === undefined) return [];
      const x = model.dateAxis ? dashboardDate(category) : (categoryIndices.get(category) ?? 0);
      return [
        {
          x,
          y: value,
          xAxisCalloutData: category,
          yAxisCalloutData: formatDashboardValue(value, tile.y_axis),
        },
      ];
    }),
  }));
  const tickValues = model.dateAxis ? undefined : model.categories.map((_, index) => index);
  return (
    <LineChart
      data={{ chartTitle: tile.title, lineChartData: lines }}
      width={width}
      height={330}
      xAxisTitle={tile.x_axis ?? undefined}
      yAxisTitle={tile.y_axis ?? undefined}
      yAxisTickFormat={yAxisTickFormat}
      xAxisTickCount={Math.min(6, model.categories.length)}
      tickValues={tickValues}
      tickFormat={model.dateAxis ? undefined : (value) => model.categories[Number(value)] ?? ''}
      enablePerfOptimization
    />
  );
}

function DashboardTable({ tile }: { tile: DashboardTile }) {
  return (
    <div className="table-scroll dashboard-table-scroll">
      <table>
        <caption className="visually-hidden">{tile.title} data</caption>
        <thead>
          <tr>
            {tile.columns.map((column) => (
              <th key={column.name} scope="col">
                {column.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {tile.rows.map((row, rowIndex) => (
            <tr key={`${tile.id}-${rowIndex}`}>
              {tile.columns.map((column, columnIndex) => (
                <td key={column.name}>{formatCell(row[columnIndex] ?? null, column.type)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatCell(value: DashboardScalar, type: string): string {
  if (value === null) return '—';
  if (/date|time/i.test(type) && typeof value === 'string') {
    const date = new Date(value);
    if (Number.isFinite(date.getTime()))
      return `${date.toLocaleString(undefined, { timeZone: 'UTC' })} UTC`;
  }
  return String(value);
}
