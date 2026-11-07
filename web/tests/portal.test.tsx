import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import type { Policy } from '../src/contracts';
import { createDemoApi } from '../src/demo';
import * as telemetry from '../src/telemetry';
import { TelemetryBoundary } from '../src/TelemetryBoundary';

const policy: Policy = {
  id: 'p1',
  name: 'Monthly budget',
  service: 'foundry',
  model: '*',
  tenant_id: '*',
  subscription_id: '*',
  limit: 25_000_000,
  period: 'month',
  metric: 'cost',
  enabled: true,
  priority: 10,
};

describe('portal telemetry outcomes', () => {
  it('logs page, refresh and failed/successful delete results without identity or record data', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const api = createDemoApi();
    const id = (await api.list('policies'))[0].id;
    vi.spyOn(api, 'remove').mockRejectedValueOnce(new Error('private-server-message'));
    wrap(
      <Portal
        api={api}
        roles={['RateLimit.Admin']}
        identity="private-identity"
        cloud="commercial"
        demo
      />,
    );
    await waitFor(() =>
      expect(log).toHaveBeenCalledWith(
        'portal_refresh',
        { outcome: 'success' },
        expect.objectContaining({ collectionCount: 8, failureCount: 0 }),
      ),
    );
    expect(log).toHaveBeenCalledWith('portal_page', { page: 'overview', outcome: 'success' });
    await user.click(screen.getByRole('button', { name: 'Budget policies' }));
    expect(log).toHaveBeenCalledWith('portal_page', { page: 'policies', outcome: 'success' });
    await user.click(screen.getByRole('button', { name: `Delete ${id}` }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('private-server-message');
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'policies',
      action: 'delete',
      outcome: 'failure',
      errorCategory: 'api',
    });
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() =>
      expect(log).toHaveBeenCalledWith('portal_configuration', {
        collection: 'policies',
        action: 'delete',
        outcome: 'success',
        errorCategory: 'none',
      }),
    );
    expect(JSON.stringify(log.mock.calls)).not.toContain('private');
    expect(JSON.stringify(log.mock.calls)).not.toContain(id);
  });

  it('logs a cancelled editor without submitting form contents', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const save = vi.fn();
    const close = vi.fn();
    wrap(<RecordEditor collection="policies" policies={[]} onSave={save} onClose={close} />);
    await user.type(screen.getByLabelText(/^Name/), 'private policy name');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(save).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'policies',
      action: 'create',
      outcome: 'cancelled',
      errorCategory: 'none',
    });
    expect(JSON.stringify(log.mock.calls)).not.toContain('private');
  });

  it('logs a static render error category and presents no raw exception details', () => {
    const log = vi.spyOn(telemetry, 'track');
    vi.spyOn(console, 'error').mockImplementation(() => {});
    function Broken(): never {
      throw new Error('private-render-record');
    }
    wrap(
      <TelemetryBoundary>
        <Broken />
      </TelemetryBoundary>,
    );
    expect(screen.getByRole('alert')).not.toHaveTextContent('private');
    expect(log).toHaveBeenCalledWith('portal_browser_error', { errorCategory: 'render_error' });
    expect(JSON.stringify(log.mock.calls)).not.toContain('private');
  });
});
function wrap(children: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
}

describe('policy and price workflows', () => {
  it('binds a policy to a registered application subscription and derives its tenant', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="policies"
        policies={[]}
        subscriptions={[
          {
            id: 'application-research',
            tenant_id: 'tenant-1',
            display_name: 'Research application',
          },
        ]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'research-budget');
    await user.type(screen.getByLabelText(/^Name/), 'Research budget');
    await user.selectOptions(
      screen.getByLabelText(/Application subscription scope/),
      'application-research',
    );
    await user.type(screen.getByLabelText(/Limit \(integer microUSD\)/), '1000000');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          subscription_id: 'application-research',
          tenant_id: 'tenant-1',
          limit: 1_000_000,
        }),
      ),
    );
    expect(save.mock.calls[0][0]).not.toHaveProperty('principal_id');
  });

  it('rejects fractional microUSD and saves an integer budget with a UTC period', async () => {
    const log = vi.spyOn(telemetry, 'track');
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="policies"
        record={policy}
        policies={[policy]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    const limit = screen.getByLabelText(/Limit \(integer microUSD\)/);
    await user.clear(limit);
    await user.type(limit, '0.5');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('safe whole number');
    expect(save).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'policies',
      action: 'update',
      outcome: 'failure',
      errorCategory: 'validation',
    });
    await user.clear(limit);
    await user.type(limit, '5000000');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          limit: 5000000,
          period: 'month',
          metric: 'cost',
        }),
      ),
    );
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'policies',
      action: 'update',
      outcome: 'success',
      errorCategory: 'none',
    });
    expect(JSON.stringify(log.mock.calls)).not.toMatch(
      /Monthly budget|p1|5000000|25000000|principal/,
    );
  });

  it('changes available accounting units when the service changes', async () => {
    const user = userEvent.setup();
    wrap(<RecordEditor collection="policies" policies={[]} onSave={vi.fn()} onClose={vi.fn()} />);
    await user.selectOptions(screen.getByLabelText(/Service/), 'document-intelligence');
    const metric = screen.getByLabelText(/Accounting unit/);
    expect(within(metric).getByRole('option', { name: 'pages' })).toBeInTheDocument();
    expect(within(metric).queryByRole('option', { name: 'tokens' })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Service/), 'language');
    expect(within(metric).getByRole('option', { name: 'text records' })).toBeInTheDocument();
  });

  it('preserves exact decimal price strings and distinguishes per-million from per-unit', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    const record = (await createDemoApi().list('prices'))[0];
    wrap(
      <RecordEditor
        collection="prices"
        record={record}
        policies={[]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/Pages · USD per page/)).toBeInTheDocument();
    const cached = screen.getByLabelText(/Cached input tokens · USD per million/);
    await user.clear(cached);
    await user.type(cached, '0.000000123456');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          cached_input_per_million: '0.000000123456',
          input_per_million: '2.50',
        }),
      ),
    );
  });

  it('rejects invalid price syntax and reports a failed API save without closing', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockRejectedValue(new Error('API denied this price version.'));
    const close = vi.fn();
    const record = (await createDemoApi().list('prices'))[0];
    wrap(
      <RecordEditor
        collection="prices"
        record={record}
        policies={[]}
        onSave={save}
        onClose={close}
      />,
    );
    const input = screen.getByLabelText(/Input tokens · USD per million/);
    await user.clear(input);
    await user.type(input, '-2');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('non-negative decimal');
    expect(save).not.toHaveBeenCalled();
    await user.clear(input);
    await user.type(input, '2.50');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('API denied');
    expect(close).not.toHaveBeenCalled();
  });

  it('requires tenant-bound assignments to reference existing policies', async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    wrap(
      <RecordEditor
        collection="assignments"
        policies={[policy]}
        subscriptions={[
          { id: 'application-1', tenant_id: 'tenant-1', display_name: 'Application one' },
        ]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'assignment-1');
    await user.selectOptions(screen.getByLabelText(/^Application subscription/), 'application-1');
    await user.type(screen.getByLabelText(/^Policy IDs/), 'does-not-exist');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Every policy ID must exist');
    expect(save).not.toHaveBeenCalled();
  });
});

describe('authorization and reporting', () => {
  it('displays the read-only application subscription registry without gateway keys', async () => {
    const user = userEvent.setup();
    wrap(
      <Portal
        api={createDemoApi()}
        roles={['RateLimit.Reader']}
        identity="Reader"
        cloud="commercial"
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Application subscriptions' }));
    const table = await screen.findByRole('table', {
      name: 'Registered application subscriptions',
    });
    expect(within(table).getByText('Research application')).toBeInTheDocument();
    expect(within(table).getByText('application-research')).toBeInTheDocument();
    expect(within(table).queryByText(/APIM|Ocp-Apim-Subscription-Key/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create subscription' })).not.toBeInTheDocument();
  });

  it('lets a reader inspect policies and estimated usage but never mutate configuration', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const save = vi.spyOn(api, 'save');
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="Reader" cloud="government" />);
    expect(await screen.findByText('Research · monthly AI budget')).toBeInTheDocument();
    expect(screen.getByText('Azure Government')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Budget policies' }));
    expect(screen.queryByRole('button', { name: /Create policy/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Edit / })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete / })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Service usage' }));
    expect(screen.getByText('Estimated / conservative')).toBeInTheDocument();
    expect(screen.queryByText(/Last-decision remaining:/)).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it('requires confirmation before an administrator deletes configuration', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const remove = vi.spyOn(api, 'remove');
    wrap(<Portal api={api} roles={['RateLimit.Admin']} identity="Admin" cloud="commercial" />);
    await screen.findByText('Research · monthly AI budget');
    await user.click(screen.getByRole('button', { name: 'Budget policies' }));
    await user.click(screen.getByRole('button', { name: 'Delete foundry-monthly' }));
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith('policies', 'foundry-monthly'));
    await waitFor(() =>
      expect(screen.queryByText('Research · monthly AI budget')).not.toBeInTheDocument(),
    );
  });

  it('does not silently overwrite an existing ID in the create workflow', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const save = vi.spyOn(api, 'save');
    wrap(<Portal api={api} roles={['RateLimit.Admin']} identity="Admin" cloud="commercial" />);
    await screen.findByText('Research · monthly AI budget');
    await user.click(screen.getByRole('button', { name: 'Budget policies' }));
    await user.click(screen.getByRole('button', { name: 'Create policy' }));
    await user.type(screen.getByLabelText(/^ID/), 'foundry-monthly');
    await user.type(screen.getByLabelText(/^Name/), 'Replacement');
    await user.type(screen.getByLabelText(/Limit \(integer microUSD\)/), '100');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This ID already exists');
    expect(save).not.toHaveBeenCalled();
  });

  it('shows API failures and retries without substituting demo data', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const list = vi.spyOn(api, 'list').mockRejectedValue(new Error('API unavailable.'));
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="Reader" cloud="commercial" />);
    await screen.findAllByText(/API unavailable/);
    expect(screen.queryByText('Research · monthly AI budget')).not.toBeInTheDocument();
    expect(screen.getByText('Policies are unavailable. Refresh to retry.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(list).toHaveBeenCalledTimes(16));
  });

  it('does not call reporting APIs for gateway-only identities', () => {
    const api = createDemoApi();
    const list = vi.spyOn(api, 'list');
    wrap(<Portal api={api} roles={['RateLimit.Gateway']} identity="Gateway" cloud="commercial" />);
    expect(screen.getByRole('heading', { name: 'Access not assigned' })).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
  });
});
