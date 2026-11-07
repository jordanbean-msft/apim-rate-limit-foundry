import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { createApi } from '../src/api';
import { CallerReport } from '../src/components/CallerReport';
import type { CallerUsage } from '../src/contracts';
import { createDemoApi } from '../src/demo';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import * as telemetry from '../src/telemetry';

const row: CallerUsage = {
  id: 'summary-stream',
  tenant_id: 'private-tenant',
  subscription_id: 'application-research',
  caller_ref: 'a'.repeat(64),
  display_label: 'Research application',
  service: 'foundry',
  model: 'model-1',
  api_protocol: 'openai-chat',
  streaming: true,
  period: 'day',
  start_at: '2030-11-05T00:00:00Z',
  end_at: '2030-11-06T00:00:00Z',
  request_count: 3,
  admitted_requests: 2,
  denied_requests: 1,
  denied_policy_counts: { 'foundry-daily': 1 },
  estimated_requests: 1,
  cost_micro_usd: 2_500_000,
  actual_cost_micro_usd: 500_000,
  conservative_cost_micro_usd: 2_000_000,
};

function wrap(children: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
}

describe('application subscription reporting', () => {
  it('uses the server-authorized route with only a UTC period, and no caller telemetry', async () => {
    const fetch = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify([row])));
    const log = vi.fn();
    const api = createApi('https://gateway.example/portal', async () => 'token', log);
    await expect(api.callers('hour')).resolves.toEqual([row]);
    expect(fetch).toHaveBeenCalledWith(
      'https://gateway.example/portal/usage/callers?period=hour',
      expect.objectContaining({ method: 'GET', cache: 'no-store', credentials: 'omit' }),
    );
    expect(log).toHaveBeenCalledWith(
      'portal_api',
      expect.objectContaining({ collection: 'callers', outcome: 'success' }),
      expect.any(Object),
    );
    expect(JSON.stringify(log.mock.calls)).not.toMatch(/private|Research/);
    expect(JSON.stringify(log.mock.calls)).not.toContain(row.caller_ref);
  });

  it('correlates subscription, label and dashboard reference with spend and configured limits', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const api = createDemoApi();
    const callers = vi.spyOn(api, 'callers').mockResolvedValue([
      row,
      {
        ...row,
        id: 'summary-nonstream',
        streaming: false,
        subscription_id: 'application-other',
        display_label: null,
        caller_ref: 'b'.repeat(64),
        denied_policy_counts: {},
      },
    ]);
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="signed-in" cloud="commercial" />);
    await screen.findByText(/Last refresh attempt/);
    await user.click(
      screen.getByRole('button', { name: 'Application subscription spend & denials' }),
    );
    const table = await screen.findByRole('table', {
      name: 'Application subscription spend and denials',
    });
    const identityRow = within(table).getByText('Research application').closest('tr')!;
    expect(identityRow).toHaveTextContent('Tenant: private-tenant');
    expect(identityRow).toHaveTextContent('Subscription ID: application-research');
    expect(identityRow).toHaveTextContent(row.caller_ref);
    expect(identityRow).toHaveTextContent('Streaming');
    expect(identityRow).toHaveTextContent('Allowed: 2 · Denied: 1');
    expect(identityRow).toHaveTextContent('Estimated liabilities: 1 requests');
    expect(identityRow).toHaveTextContent('foundry-daily: 1');
    expect(identityRow).toHaveTextContent('Configured limit: $25.00 / day');
    expect(identityRow).toHaveTextContent('Actual: $0.50');
    expect(identityRow).toHaveTextContent('Conservative: $2.00');
    expect(screen.getByText(/Non-streaming/)).toBeInTheDocument();
    const searchBox = screen.getByRole('textbox', {
      name: 'Search application subscription report',
    });
    await user.type(searchBox, row.caller_ref);
    expect(within(table).queryByText('Subscription ID: application-other')).not.toBeInTheDocument();
    expect(within(table).getByText('Research application')).toBeInTheDocument();
    await user.clear(searchBox);
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Application subscription' }),
      'application-research',
    );
    expect(within(table).queryByText('Subscription ID: application-other')).not.toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'Reporting UTC period' }),
      'hour',
    );
    await waitFor(() => expect(callers).toHaveBeenLastCalledWith('hour'));
    expect(JSON.stringify(log.mock.calls)).not.toMatch(/private|Research|binding-budget/);
    expect(JSON.stringify(log.mock.calls)).not.toContain(row.caller_ref);
    expect(screen.queryByRole('button', { name: 'Create assignment' })).not.toBeInTheDocument();
  });

  it('shows report errors without stale identities or substituted fixtures and retries', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const callers = vi
      .spyOn(api, 'callers')
      .mockRejectedValueOnce(new Error('private-error'))
      .mockResolvedValueOnce([row]);
    wrap(<CallerReport api={api} refreshKey="initial" />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Application subscription report unavailable',
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent('private-error');
    expect(screen.queryByText('Research application')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry application subscription report' }));
    expect(await screen.findByText('Research application')).toBeInTheDocument();
    expect(callers).toHaveBeenCalledTimes(2);
  });

  it('never loads subscription reports for a gateway-only identity', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const callers = vi.spyOn(api, 'callers');
    wrap(<Portal api={api} roles={['RateLimit.Gateway']} identity="gateway" cloud="commercial" />);
    await user.click(
      screen.getByRole('button', { name: 'Application subscription spend & denials' }),
    );
    expect(screen.getByRole('heading', { name: 'Access not assigned' })).toBeInTheDocument();
    expect(callers).not.toHaveBeenCalled();
  });

  it('allows an administrator to configure a display label without logging it', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="assignments"
        subscriptions={[
          {
            id: 'application-research',
            tenant_id: 'private-tenant',
            display_name: 'Research application',
          },
        ]}
        policies={[
          {
            id: 'policy-1',
            name: 'Budget',
            service: 'foundry',
            model: '*',
            subscription_id: '*',
            limit: 1,
            period: 'day',
            metric: 'requests',
            enabled: true,
            priority: 10,
          },
        ]}
        record={{
          id: 'assignment-1',
          tenant_id: 'private-tenant',
          subscription_id: 'application-research',
          policy_ids: ['policy-1'],
          reader_principal_ids: [],
        }}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText('Display label (optional)'), 'Research application');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        tenant_id: 'private-tenant',
        subscription_id: 'application-research',
        reader_principal_ids: [],
        display_label: 'Research application',
      }),
    );
    expect(JSON.stringify(log.mock.calls)).not.toMatch(/private|Research/);
  });
});
