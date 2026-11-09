import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import type { Assignment, Organization } from '../src/contracts';
import { createDemoApi } from '../src/demo';
import * as telemetry from '../src/telemetry';
import { TelemetryBoundary } from '../src/TelemetryBoundary';

const department: Organization = {
  id: 'engineering',
  tenant_id: 'tenant-1',
  kind: 'department',
  name: 'Engineering',
  business_unit: 'Product',
  cost_center: 'CC-4100',
  enabled: true,
};
const team: Organization = {
  id: 'platform',
  tenant_id: 'tenant-1',
  kind: 'team',
  name: 'Platform',
  department_id: 'engineering',
  business_unit: 'Product',
  cost_center: 'CC-4100',
  enabled: true,
};
const assignment: Assignment = {
  id: 'alice-assignment',
  tenant_id: 'tenant-1',
  principal_id: 'entra-object-id',
  team_id: 'platform',
  department_id: 'engineering',
  display_label: 'Alice',
  enabled: true,
};
function wrap(children: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
}

describe('portal telemetry outcomes', () => {
  it('logs page, refresh and failed/successful delete results without identity or record data', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const api = createDemoApi();
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
        expect.objectContaining({ collectionCount: 7, failureCount: 0 }),
      ),
    );
    expect(log).toHaveBeenCalledWith('portal_page', { page: 'overview', outcome: 'success' });
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    await user.click(screen.getByRole('button', { name: 'Delete engineering-monthly' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('private-server-message');
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'budgets',
      action: 'delete',
      outcome: 'failure',
      errorCategory: 'api',
    });
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));
    await waitFor(() =>
      expect(log).toHaveBeenCalledWith('portal_configuration', {
        collection: 'budgets',
        action: 'delete',
        outcome: 'success',
        errorCategory: 'none',
      }),
    );
    expect(JSON.stringify(log.mock.calls)).not.toContain('private');
    expect(JSON.stringify(log.mock.calls)).not.toContain('engineering-monthly');
  });

  it('logs a cancelled editor without submitting form contents', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const save = vi.fn();
    const close = vi.fn();
    wrap(
      <RecordEditor
        collection="budgets"
        organizations={[department, team]}
        assignments={[assignment]}
        models={[]}
        onSave={save}
        onClose={close}
      />,
    );
    await user.type(screen.getByLabelText(/^Budget name/), 'private budget');
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(save).not.toHaveBeenCalled();
    expect(close).toHaveBeenCalledOnce();
    expect(log).toHaveBeenCalledWith('portal_configuration', {
      collection: 'budgets',
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
    expect(log).toHaveBeenCalledWith(
      'portal_browser_error',
      expect.objectContaining({ errorCategory: 'render_error', errorName: 'Error' }),
    );
    expect(JSON.stringify(log.mock.calls)).not.toContain('private');
  });
});

describe('monthly budgets, assignments and price cards', () => {
  it('converts an entered decimal USD limit to integer micro-USD exactly', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="budgets"
        organizations={[department, team]}
        assignments={[assignment]}
        models={[
          {
            id: 'openai-chat:gpt-4o',
            model: 'gpt-4o',
            api_protocol: 'openai-chat',
            deployment_name: 'chat',
            price_version: 'v1',
            max_input_tokens: 1000,
            max_output_tokens: 1000,
          },
        ]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'user-budget');
    await user.type(screen.getByLabelText(/^Tenant ID/), 'tenant-1');
    await user.type(screen.getByLabelText(/^Budget name/), 'Alice monthly');
    await user.type(screen.getByLabelText(/Budget subject ID/), 'entra-object-id');
    await user.type(screen.getByLabelText(/Monthly budget \(USD\)/), '12.340056');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'user-budget',
          subject_type: 'user',
          subject_id: 'entra-object-id',
          limit_micro_usd: 12_340_056,
        }),
      ),
    );
  });

  it.each(['0.0000001', '1e3', '-1', '9007199255.999999'])(
    'rejects unsafe or inexact monthly USD value %s',
    async (value) => {
      const user = userEvent.setup();
      const save = vi.fn();
      wrap(
        <RecordEditor
          collection="budgets"
          organizations={[department, team]}
          assignments={[assignment]}
          models={[]}
          onSave={save}
          onClose={vi.fn()}
        />,
      );
      await user.type(screen.getByLabelText(/^ID/), 'valid-id');
      await user.type(screen.getByLabelText(/^Tenant ID/), 'tenant-1');
      await user.type(screen.getByLabelText(/^Budget name/), 'Monthly');
      await user.type(screen.getByLabelText(/Budget subject ID/), 'entra-object-id');
      await user.type(screen.getByLabelText(/Monthly budget \(USD\)/), value);
      await user.click(screen.getByRole('button', { name: 'Save changes' }));
      expect(await screen.findByRole('alert')).toHaveTextContent(/budget|large/);
      expect(save).not.toHaveBeenCalled();
    },
  );

  it('derives assignment department from the enabled parent department of its team', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="assignments"
        organizations={[department, team]}
        assignments={[]}
        models={[]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'alice');
    await user.type(screen.getByLabelText(/^Tenant ID/), 'tenant-1');
    await user.type(screen.getByLabelText(/Entra principal ID/), 'entra-object-id');
    await user.type(screen.getByLabelText(/^Team ID/), 'platform');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          principal_id: 'entra-object-id',
          team_id: 'platform',
          department_id: 'engineering',
        }),
      ),
    );
  });

  it('keeps OpenAI price rates as exact decimal strings and excludes other billing units', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="prices"
        organizations={[]}
        assignments={[]}
        models={[
          {
            id: 'openai-chat:gpt-4o',
            model: 'gpt-4o',
            api_protocol: 'openai-chat',
            deployment_name: 'chat',
            price_version: 'v1',
            max_input_tokens: 1000,
            max_output_tokens: 1000,
          },
        ]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'rate-v1');
    await user.selectOptions(screen.getByLabelText(/Model alias/), 'gpt-4o');
    await user.type(screen.getByLabelText(/^Price version/), 'v1');
    const rate = screen.getByLabelText(/Cached input/);
    await user.clear(rate);
    await user.type(rate, '0.000000123456');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          model: 'gpt-4o',
          cached_input_per_million: '0.000000123456',
        }),
      ),
    );
    expect(
      screen.queryByText(/per page|text record|per request|Anthropic/i),
    ).not.toBeInTheDocument();
  });
});

describe('authorization, MTD status and exports', () => {
  it('shows actual month-to-date spend and the explicit soft-cap warning', async () => {
    const user = userEvent.setup();
    wrap(
      <Portal
        api={createDemoApi()}
        roles={['RateLimit.Reader']}
        identity="reader"
        cloud="commercial"
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    const table = await screen.findByRole('table', {
      name: 'Monthly actual spend and remaining budgets',
    });
    expect(within(table).getByText(/Engineering monthly/)).toBeInTheDocument();
    expect(table).toHaveTextContent('$0.90');
    expect(screen.getByText(/concurrent in-flight requests can overshoot/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Create/ })).not.toBeInTheDocument();
  });

  it('renders unknown chargeback counts without inventing zero tokens or dollars', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    vi.spyOn(api, 'chargeback').mockResolvedValue([
      {
        business_unit: 'Product',
        cost_center: 'CC-4100',
        department_id: 'engineering',
        team_id: 'platform',
        user_ref: 'opaque-user',
        subscription_id: 'application',
        model: 'gpt-4.1-mini',
        month: '2030-01',
        input_tokens: null,
        cached_input_tokens: null,
        output_tokens: null,
        cost_micro_usd: null,
        unknown_requests: 1,
      },
    ]);
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />);
    await user.click(screen.getByRole('button', { name: 'Chargeback' }));
    const report = await screen.findByRole('table', { name: 'Monthly chargeback report' });
    expect(await within(report).findByText('Unknown — no actual usage reported')).toBeInTheDocument();
    expect(report).toHaveTextContent('Unknown · Unknown · Unknown');
    expect(report).not.toHaveTextContent('$0.00');
  });

  it('lets a reader view chargeback and export both contract formats', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const chargeback = vi.spyOn(api, 'chargeback');
    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:export');
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />);
    await user.click(screen.getByRole('button', { name: 'Chargeback' }));
    expect(
      await screen.findByRole('table', { name: 'Monthly chargeback report' }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Export JSON' }));
    await waitFor(() => expect(chargeback).toHaveBeenCalledWith(expect.any(String), 'json'));
    expect(createUrl).toHaveBeenCalledOnce();
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(chargeback).toHaveBeenCalledWith(expect.any(String), 'csv'));
    expect(createUrl).toHaveBeenCalledTimes(2);
    expect(revokeUrl).toHaveBeenCalledTimes(2);
    expect(anchorClick).toHaveBeenCalledTimes(2);
    createUrl.mockRestore();
    revokeUrl.mockRestore();
    anchorClick.mockRestore();
  });

  it('does not request portal data for gateway-only identities', () => {
    const api = createDemoApi();
    const list = vi.spyOn(api, 'list');
    wrap(<Portal api={api} roles={['RateLimit.Gateway']} identity="Gateway" cloud="commercial" />);
    expect(screen.getByRole('heading', { name: 'Access not assigned' })).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
  });

  it('keeps API failures visible without substituting demo records', async () => {
    const api = createDemoApi();
    vi.spyOn(api, 'list').mockRejectedValue(new Error('API unavailable.'));
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="Reader" cloud="commercial" />);
    expect(await screen.findAllByText(/API unavailable/)).not.toHaveLength(0);
    expect(screen.queryByText('gpt-4o')).not.toBeInTheDocument();
  });
});
