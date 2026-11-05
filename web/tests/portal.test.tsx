import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import type { Policy } from '../src/contracts';
import { createDemoApi } from '../src/demo';

const policy: Policy = {
  id: 'p1',
  name: 'Monthly budget',
  service: 'foundry',
  model: '*',
  tenant_id: '*',
  principal_id: '*',
  limit: 25_000_000,
  period: 'month',
  metric: 'cost',
  enabled: true,
  priority: 10,
};
function wrap(children: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
}

describe('policy and price workflows', () => {
  it('rejects fractional microUSD and saves an integer budget with a UTC period', async () => {
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
      <RecordEditor collection="assignments" policies={[policy]} onSave={save} onClose={vi.fn()} />,
    );
    await user.type(screen.getByLabelText(/^ID/), 'assignment-1');
    await user.type(screen.getByLabelText(/^Tenant ID/), 'tenant-1');
    await user.type(screen.getByLabelText(/^Principal ID/), 'principal-1');
    await user.type(screen.getByLabelText(/^Policy IDs/), 'does-not-exist');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Every policy ID must exist');
    expect(save).not.toHaveBeenCalled();
  });
});

describe('authorization and reporting', () => {
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
    expect(screen.getByText(/Last-decision remaining: 182300000/)).toBeInTheDocument();
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
    await waitFor(() => expect(list).toHaveBeenCalledTimes(12));
  });

  it('does not call reporting APIs for gateway-only identities', () => {
    const api = createDemoApi();
    const list = vi.spyOn(api, 'list');
    wrap(<Portal api={api} roles={['RateLimit.Gateway']} identity="Gateway" cloud="commercial" />);
    expect(screen.getByRole('heading', { name: 'Access not assigned' })).toBeInTheDocument();
    expect(list).not.toHaveBeenCalled();
  });
});
