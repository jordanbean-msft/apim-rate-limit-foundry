import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import demoFixtures from '../../demo/data/office.json';
import seedModels from '../../examples/model-registry.json';
import seedPrices from '../../examples/prices.json';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import type { Assignment, Organization } from '../src/contracts';
import { createDemoApi } from './fixtures/api';
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

describe('Office-themed sample data', () => {
  it('keeps portal and seed memberships, budget subjects, and model pricing consistent', async () => {
    const api = createDemoApi(demoFixtures);
    const organizations = await api.list('organizations');
    const assignments = await api.list('assignments');
    const budgets = await api.list('budgets');
    const models = await api.list('models');
    const prices = await api.list('prices');

    expect(prices).toEqual(seedPrices);
    expect(
      budgets.map(({ id, subject_type, subject_id }) => ({ id, subject_type, subject_id })),
    ).toEqual(
      expect.arrayContaining(
        demoFixtures.collections.budgets.map(({ id, subject_type, subject_id }) => ({
          id,
          subject_type,
          subject_id,
        })),
      ),
    );
    for (const assignment of assignments) {
      const team = organizations.find((organization) => organization.id === assignment.team_id);
      expect(team).toMatchObject({
        kind: 'team',
        tenant_id: assignment.tenant_id,
        department_id: assignment.department_id,
      });
      expect(organizations).toContainEqual(
        expect.objectContaining({
          id: assignment.department_id,
          tenant_id: assignment.tenant_id,
          kind: 'department',
        }),
      );
    }
    for (const budget of budgets) {
      const subjects =
        budget.subject_type === 'user'
          ? assignments.map((assignment) => assignment.principal_id)
          : organizations
              .filter((organization) => organization.kind === budget.subject_type)
              .map((organization) => organization.id);
      expect(subjects).toContain(budget.subject_id);
    }
    for (const model of models) {
      expect(seedModels).toMatchObject({
        [model.id]: expect.objectContaining({
          model: model.model,
          api_protocol: model.api_protocol,
          price_version: model.price_version,
          max_input_tokens: model.max_input_tokens,
          max_output_tokens: model.max_output_tokens,
        }),
      });
      expect(prices).toContainEqual(
        expect.objectContaining({
          model: model.model,
          version: model.price_version,
        }),
      );
    }
  });

  it('keeps usage and chargeback dimensions and actual costs aligned with the price cards', async () => {
    const api = createDemoApi(demoFixtures);
    const usage = await api.list('usage');
    const prices = await api.list('prices');
    const report = await api.chargeback(usage[0].month, 'json');
    expect(Array.isArray(report)).toBe(true);
    if (!Array.isArray(report)) throw new Error('Expected JSON chargeback rows');

    for (const record of usage) {
      const row = report.find(
        (candidate) => candidate.team_id === record.team_id && candidate.model === record.model,
      );
      expect(row).toMatchObject({
        department_id: record.department_id,
        business_unit: record.business_unit,
        cost_center: record.cost_center,
        user_ref: record.user_ref,
        subscription_id: record.subscription_id,
        input_tokens: record.input_tokens,
        cached_input_tokens: record.cached_input_tokens,
        output_tokens: record.output_tokens,
        cost_micro_usd: record.cost_micro_usd,
        unknown_requests: record.status === 'usage_unknown' ? 1 : 0,
      });
      if (record.status === 'actual') {
        const price = prices.find(
          (candidate) =>
            candidate.model === record.model && candidate.version === record.price_version,
        );
        if (!price) throw new Error('Usage has no matching price card');
        if (
          record.input_tokens === null ||
          record.cached_input_tokens === null ||
          record.output_tokens === null
        )
          throw new Error('Actual usage requires token counts');
        expect(record.cost_micro_usd).toBe(
          Math.ceil(
            (record.input_tokens - record.cached_input_tokens) * Number(price.input_per_million) +
              record.cached_input_tokens * Number(price.cached_input_per_million) +
              record.output_tokens * Number(price.output_per_million),
          ),
        );
      }
    }
  });
});

describe('recommended actions', () => {
  it('turns a coverage gap into a prefilled path to create a budget', async () => {
    const user = userEvent.setup();
    wrap(
      <Portal
        api={createDemoApi(demoFixtures)}
        roles={['RateLimit.Admin']}
        identity="admin"
        cloud="commercial"
      />,
    );
    const panel = await screen.findByRole('region', { name: 'Recommended actions' });
    expect(within(panel).getByText(/1 team without a monthly budget/)).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Create team budget' }));
    expect(
      await screen.findByRole('heading', { name: /Create monthly budget/ }),
    ).toBeInTheDocument();
  });

  it('gives readers guidance without administrator-only actions', async () => {
    wrap(
      <Portal
        api={createDemoApi(demoFixtures)}
        roles={['RateLimit.Reader']}
        identity="reader"
        cloud="commercial"
      />,
    );
    const panel = await screen.findByRole('region', { name: 'Recommended actions' });
    expect(within(panel).getByText(/finished without provider usage/)).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Create/ })).not.toBeInTheDocument();
  });
});

describe('portal telemetry outcomes', () => {
  it('logs page, refresh and failed/successful delete results without identity or record data', async () => {
    const user = userEvent.setup();
    const log = vi.spyOn(telemetry, 'track');
    const api = createDemoApi(demoFixtures);
    vi.spyOn(api, 'remove').mockRejectedValueOnce(new Error('private-server-message'));
    wrap(
      <Portal
        api={api}
        roles={['RateLimit.Admin']}
        identity="private-identity"
        cloud="commercial"
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
    await user.click(screen.getByRole('button', { name: 'Delete sales-department-monthly' }));
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
    expect(JSON.stringify(log.mock.calls)).not.toContain('sales-department-monthly');
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

describe('optional cache-write price', () => {
  const models = [
    {
      id: 'openai-chat:gpt-4o',
      model: 'gpt-4o',
      api_protocol: 'openai-chat' as const,
      deployment_name: 'chat',
      price_version: 'v1',
      max_input_tokens: 1000,
      max_output_tokens: 1000,
    },
  ];

  it.each([
    ['', undefined],
    ['1.25', '1.25'],
  ])('submits cache-write rate %j as %j', async (typed, expected) => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="prices"
        organizations={[]}
        assignments={[]}
        models={models}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'rate-v1');
    await user.selectOptions(screen.getByLabelText(/Model alias/), 'gpt-4o');
    await user.type(screen.getByLabelText(/^Price version/), 'v1');
    if (typed) await user.type(screen.getByLabelText(/Cache write/), typed);
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].cache_write_per_million).toBe(expected);
  });
});

describe('authorization, MTD status and exports', () => {
  it('combines admin budget status and configuration in one searchable, editable grid', async () => {
    const user = userEvent.setup();
    const api = createDemoApi(demoFixtures);
    const status = await api.budgetStatus();
    vi.spyOn(api, 'budgetStatus').mockResolvedValue(status.reverse());
    wrap(<Portal api={api} roles={['RateLimit.Admin']} identity="admin" cloud="commercial" />);
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    const table = await screen.findByRole('table', { name: 'budgets' });
    const name = await within(table).findByText('Sales monthly');
    const row = within(name.closest('tr')!);
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(row.getByText('$250.00')).toBeInTheDocument();
    expect(row.getByText('$0.005424')).toBeInTheDocument();
    expect(row.getByText('$249.994576')).toBeInTheDocument();
    expect(screen.getByText(/UTC calendar month/)).toBeInTheDocument();
    expect(row.getByText('Enabled')).toBeInTheDocument();
    expect(
      row.getByRole('button', { name: 'Delete sales-department-monthly' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/concurrent in-flight requests can overshoot/)).toBeInTheDocument();
    await user.type(
      screen.getByRole('textbox', { name: 'Search budgets' }),
      'sales-department-monthly',
    );
    expect(within(table).getAllByRole('row')).toHaveLength(2);
    await user.click(row.getByRole('button', { name: 'Edit sales-department-monthly' }));
    expect(await screen.findByLabelText(/^Budget name/)).toHaveValue('Sales monthly');
  });

  it('keeps disabled and missing-status budgets visible without inventing spending totals', async () => {
    const user = userEvent.setup();
    const api = createDemoApi(demoFixtures);
    const budgets = await api.list('budgets');
    await api.save('budgets', { ...budgets[0], enabled: false });
    vi.spyOn(api, 'budgetStatus').mockResolvedValue([]);
    wrap(<Portal api={api} roles={['RateLimit.Admin']} identity="admin" cloud="commercial" />);
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    const disabled = await screen.findByText('Sales monthly');
    const disabledRow = within(disabled.closest('tr')!);
    expect(disabledRow.getByText('Disabled')).toBeInTheDocument();
    expect(disabledRow.getAllByText('Not applicable')).toHaveLength(2);
    expect(
      disabledRow.getByRole('button', { name: 'Edit sales-department-monthly' }),
    ).toBeInTheDocument();
    const enabled = screen.getByText('Scranton Sales monthly');
    expect(within(enabled.closest('tr')!).getAllByText('Unavailable')).toHaveLength(2);
    expect(screen.getAllByRole('table')).toHaveLength(1);
  });

  it('keeps admin budget actions available when the spend-status request fails', async () => {
    const user = userEvent.setup();
    const api = createDemoApi(demoFixtures);
    vi.spyOn(api, 'budgetStatus').mockRejectedValue(new Error('Spend status unavailable.'));
    wrap(<Portal api={api} roles={['RateLimit.Admin']} identity="admin" cloud="commercial" />);
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    expect(await screen.findByText(/Spend status unavailable\./)).toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'budgets' });
    expect(within(table).getAllByText('Unavailable')).toHaveLength(6);
    expect(
      within(table).getByRole('button', { name: 'Edit sales-department-monthly' }),
    ).toBeInTheDocument();
    expect(table).not.toHaveTextContent('$0.00');
    expect(screen.getAllByRole('table')).toHaveLength(1);
  });

  it('shows actual month-to-date spend and the explicit soft-cap warning', async () => {
    const user = userEvent.setup();
    wrap(
      <Portal
        api={createDemoApi(demoFixtures)}
        roles={['RateLimit.Reader']}
        identity="reader"
        cloud="commercial"
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Monthly budgets' }));
    const table = await screen.findByRole('table', {
      name: 'Monthly actual spend and remaining budgets',
    });
    expect(within(table).getByText('Sales monthly')).toBeInTheDocument();
    expect(table).toHaveTextContent('$0.90');
    expect(screen.getByText(/concurrent in-flight requests can overshoot/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Create/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(within(table).queryByRole('columnheader', { name: 'Actions' })).not.toBeInTheDocument();
  });

  it('renders unknown chargeback counts without inventing zero tokens or dollars', async () => {
    const user = userEvent.setup();
    const api = createDemoApi(demoFixtures);
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
    expect(
      await within(report).findByText('Unknown — no actual usage reported'),
    ).toBeInTheDocument();
    expect(report).toHaveTextContent('Unknown · Unknown · Unknown');
    expect(report).not.toHaveTextContent('$0.00');
  });

  it('lets a reader view chargeback and export both contract formats', async () => {
    const user = userEvent.setup();
    const api = createDemoApi(demoFixtures);
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
    const api = createDemoApi(demoFixtures);
    const list = vi.spyOn(api, 'list');
    wrap(<Portal api={api} roles={['RateLimit.Gateway']} identity="Gateway" cloud="commercial" />);
    expect(screen.getByRole('heading', { name: 'Access not assigned' })).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
  });

  it('keeps API failures visible without substituting demo records', async () => {
    const api = createDemoApi(demoFixtures);
    vi.spyOn(api, 'list').mockRejectedValue(new Error('API unavailable.'));
    wrap(<Portal api={api} roles={['RateLimit.Reader']} identity="Reader" cloud="commercial" />);
    expect(await screen.findAllByText(/API unavailable/)).not.toHaveLength(0);
    expect(screen.queryByText('gpt-5.4')).not.toBeInTheDocument();
  });
});
