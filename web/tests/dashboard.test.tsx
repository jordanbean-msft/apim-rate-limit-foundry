import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Dashboard } from '../src/components/Dashboard';
import { Portal } from '../src/Portal';
import type { DashboardTile, PortalApi } from '../src/contracts';
import { createDemoApi } from '../src/demo';

const tableTile = (title: string, rows: DashboardTile['rows'] = [['ok']]): DashboardTile => ({
  id: title,
  title,
  chart: '',
  x_axis: null,
  y_axis: null,
  split_by: null,
  columns: [{ name: 'Result', type: 'string' }],
  rows,
  error: null,
  truncated: false,
});
const wrap = (children: React.ReactNode) =>
  render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
const dashboardApi = (dashboard: PortalApi['dashboard']) => ({ dashboard }) as unknown as PortalApi;

describe('Azure dashboard page', () => {
  afterEach(() => {
    Reflect.deleteProperty(SVGElement.prototype, 'getComputedTextLength');
  });

  it('renders actual token and accounting charts before supporting grids', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      measureText: (text: string) => ({ width: text.length * 8 }),
    } as CanvasRenderingContext2D);
    Object.defineProperty(SVGElement.prototype, 'getComputedTextLength', {
      configurable: true,
      value(this: SVGElement) {
        return (this.textContent?.length ?? 0) * 8;
      },
    });
    const tokens: DashboardTile = {
      ...tableTile('Actual token composition by model'),
      chart: 'StackedColumn',
      x_axis: 'Model',
      y_axis: 'Tokens',
      split_by: 'TokenType',
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'TokenType', type: 'string' },
        { name: 'Tokens', type: 'long' },
      ],
      rows: [
        ['sample-model', 'Cached input', 1200],
        ['sample-model', 'Uncached input', 300],
        ['sample-model', 'Output', 50],
      ],
    };
    const lifecycle: DashboardTile = {
      ...tokens,
      id: 'lifecycle',
      title: 'Function accounting',
      chart: 'Column',
      y_axis: 'Requests',
      split_by: 'Stage',
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'Stage', type: 'string' },
        { name: 'Requests', type: 'long' },
      ],
      rows: [
        ['sample-model', 'Admitted', 8],
        ['sample-model', 'Finalized actual', 7],
        ['sample-model', 'Recorded unknown', 1],
      ],
    };
    const cache: DashboardTile = {
      ...tokens,
      id: 'cache',
      title: 'Provider prompt-cache percentage',
      chart: 'Column',
      y_axis: 'CacheHitPercent',
      split_by: null,
      columns: [
        { name: 'Model', type: 'string' },
        { name: 'CacheHitPercent', type: 'real' },
      ],
      rows: [['sample-model', 80]],
    };
    wrap(
      <Dashboard
        api={dashboardApi(
          vi.fn().mockResolvedValue([tableTile('Supporting evidence'), tokens, lifecycle, cache]),
        )}
        fixtureMode={false}
      />,
    );
    const chart = await screen.findByRole('img', {
      name: 'Actual token composition by model. Model by Tokens.',
    });
    expect(chart.querySelector('svg')).not.toBeNull();
    expect(
      screen
        .getByRole('img', { name: 'Function accounting. Model by Requests.' })
        .querySelector('svg'),
    ).not.toBeNull();
    const charts = screen.getByRole('region', { name: 'Operational charts' });
    const details = screen.getByRole('region', { name: 'Supporting detail grids' });
    expect(charts.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(charts).getAllByText(/View data table/)).toHaveLength(3);
    expect(screen.queryByText('Undefined')).not.toBeInTheDocument();
    expect(
      screen.getByText(/Blocked requests have no measured provider tokens/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Lifecycle stages overlap/)).toBeInTheDocument();
  });

  it('shows loading, selectable periods, and accessible data details', async () => {
    const dashboard = vi.fn().mockResolvedValue([tableTile('Native dashboard table')]);
    wrap(<Dashboard api={dashboardApi(dashboard)} fixtureMode={false} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading Azure dashboard tiles');
    expect(await screen.findByText('Native dashboard table')).toBeInTheDocument();
    expect(dashboard).toHaveBeenCalledWith('24h');
    const range = screen.getByRole('combobox', { name: 'Dashboard time range' });
    fireEvent.change(range, { target: { value: '1h' } });
    await waitFor(() => expect(dashboard).toHaveBeenLastCalledWith('1h'));
    await screen.findByRole('columnheader', { name: 'Result' });
  });

  it('shows global retry and empty states without substituting fixture data', async () => {
    const dashboard = vi
      .fn()
      .mockRejectedValueOnce(new Error('Service unavailable (HTTP 503).'))
      .mockResolvedValueOnce([]);
    wrap(<Dashboard api={dashboardApi(dashboard)} fixtureMode={false} />);
    expect(await screen.findByText(/Service unavailable \(HTTP 503\)/)).toBeInTheDocument();
    expect(screen.queryByText(/fixture/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh dashboard' }));
    expect(await screen.findByText('No dashboard tiles returned')).toBeInTheDocument();
  });

  it('ignores a stale response after a newer period selection', async () => {
    let resolveFirst!: (tiles: DashboardTile[]) => void;
    const dashboard = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<DashboardTile[]>((resolve) => {
            resolveFirst = resolve;
          }),
      )
      .mockResolvedValueOnce([tableTile('Newest range')]);
    wrap(<Dashboard api={dashboardApi(dashboard)} fixtureMode={false} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Dashboard time range' }), {
      target: { value: '7d' },
    });
    expect(await screen.findByText('Newest range')).toBeInTheDocument();
    await act(async () => {
      resolveFirst([tableTile('Stale range')]);
    });
    expect(screen.getByText('Newest range')).toBeInTheDocument();
    expect(screen.queryByText('Stale range')).not.toBeInTheDocument();
  });

  it('renders per-tile errors, empty results and truncation notices independently', async () => {
    const tiles = [
      { ...tableTile('Tile error'), error: 'Query failed safely.' },
      tableTile('Empty tile', []),
      { ...tableTile('Bounded tile'), truncated: true },
    ];
    wrap(<Dashboard api={dashboardApi(vi.fn().mockResolvedValue(tiles))} fixtureMode />);
    expect(
      screen.getByText(/Local fixture mode — these charts are illustrative fixtures/),
    ).toBeInTheDocument();
    expect(await screen.findByText('Query failed safely.')).toBeInTheDocument();
    expect(screen.getByText('No data for this time range.')).toBeInTheDocument();
    expect(
      screen.getAllByText(/Limited to 1,000 results|limited to 1,000 results/).length,
    ).toBeGreaterThan(0);
  });

  it('keeps dashboard navigation administrator-only and never requests it for readers', async () => {
    const api = createDemoApi();
    const dashboard = vi.spyOn(api, 'dashboard');
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />);
    expect(screen.queryByRole('button', { name: 'Azure dashboard' })).not.toBeInTheDocument();
    expect(dashboard).not.toHaveBeenCalled();
    const adminApi = createDemoApi();
    const adminDashboard = vi.spyOn(adminApi, 'dashboard').mockResolvedValue([]);
    wrap(<Portal api={adminApi} roles={['RateLimit.Admin']} identity="admin" cloud="commercial" />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Azure dashboard' })[0]);
    await waitFor(() => expect(adminDashboard).toHaveBeenCalledWith('24h'));
  });
});
