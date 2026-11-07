import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
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
