import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { createApi } from '../src/api';
import { Portal } from '../src/Portal';
import { RecordEditor } from '../src/RecordEditor';
import { createDemoApi } from '../src/demo';

describe('model discovery', () => {
  it('displays protocol-scoped aliases, provider deployments and distinct pinned prices for readers', async () => {
    const user = userEvent.setup();
    render(
      <FluentProvider theme={webLightTheme}>
        <Portal
          api={createDemoApi()}
          roles={['RateLimit.Reader']}
          identity="reader"
          cloud="commercial"
        />
      </FluentProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Model inventory' }));
    const table = await screen.findByRole('table', { name: 'Registered models' });
    await waitFor(() => expect(within(table).getAllByText('sample-model')).toHaveLength(2));
    const fast = within(table).getByText('sample-fast').closest('tr')!;
    expect(within(fast).getByText('provider-fast-deployment')).toBeInTheDocument();
    expect(within(fast).getByText(/Input \$0.50 · Output \$2.00/)).toBeInTheDocument();
    const standard = within(table).getByText('provider-chat-standard').closest('tr')!;
    expect(within(standard).getByText(/Input \$2.50 · Output \$10.00/)).toBeInTheDocument();
    expect(within(table).queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not replace discovery failures with fixtures and marks unavailable prices unknown', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const original = api.list.bind(api);
    vi.spyOn(api, 'list').mockImplementation((collection) =>
      collection === 'models' ? Promise.reject(new Error('offline')) : original(collection),
    );
    render(
      <FluentProvider theme={webLightTheme}>
        <Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />
      </FluentProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Model inventory' }));
    expect(await screen.findByText(/Model inventory unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('provider-fast-deployment')).not.toBeInTheDocument();
  });

  it('reports absent or unavailable price cards rather than free prices', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const original = api.list.bind(api);
    vi.spyOn(api, 'list').mockImplementation((collection) =>
      collection === 'prices' ? Promise.reject(new Error('offline')) : original(collection),
    );
    render(
      <FluentProvider theme={webLightTheme}>
        <Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />
      </FluentProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Model inventory' }));
    expect((await screen.findAllByText('Price catalog unavailable')).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Input \$0.50/)).not.toBeInTheDocument();
  });

  it('marks a missing pinned price as not configured', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    await api.remove('prices', 'sample-fast-price-v1');
    render(
      <FluentProvider theme={webLightTheme}>
        <Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />
      </FluentProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Model inventory' }));
    const model = await screen.findByText('sample-fast');
    expect(within(model.closest('tr')!).getByText('Price not configured')).toBeInTheDocument();
  });

  it('resolves shared aliases using each protocol price pin', async () => {
    const user = userEvent.setup();
    const api = createDemoApi();
    const basePrice = (await api.list('prices'))[0];
    await api.save('prices', {
      ...basePrice,
      id: 'alternate-price',
      version: 'alternate',
      input_per_million: '9.00',
    });
    const original = api.list.bind(api);
    vi.spyOn(api, 'list').mockImplementation(async (collection) => {
      const records = await original(collection);
      if (collection === 'models')
        return records.map((record) =>
          record.id === 'openai-responses:sample-model'
            ? { ...record, price_version: 'alternate' }
            : record,
        ) as typeof records;
      return records;
    });
    render(
      <FluentProvider theme={webLightTheme}>
        <Portal api={api} roles={['RateLimit.Reader']} identity="reader" cloud="commercial" />
      </FluentProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Model inventory' }));
    const deployment = await screen.findByText('provider-responses-standard');
    expect(within(deployment.closest('tr')!).getByText(/Input \$9.00/)).toBeInTheDocument();
  });

  it('offers deduplicated aliases and wildcard while keeping manual entries', async () => {
    const models = await createDemoApi().list('models');
    render(
      <FluentProvider theme={webLightTheme}>
        <RecordEditor
          collection="policies"
          policies={[]}
          models={models}
          onSave={vi.fn()}
          onClose={vi.fn()}
        />
      </FluentProvider>,
    );
    const field = screen.getByLabelText(/Model or deployment/);
    const list = document.getElementById(field.getAttribute('list')!)!;
    expect(list.querySelectorAll('option[value="sample-model"]')).toHaveLength(1);
    expect(list.querySelector('option[value="sample-model"]')).toHaveAttribute(
      'label',
      'openai-chat, openai-responses',
    );
    expect(list.querySelector('option[value="*"]')).not.toBeNull();
    const user = userEvent.setup();
    await user.clear(field);
    await user.type(field, 'legacy-model');
    expect(field).toHaveValue('legacy-model');
  });

  it('fetches the protected model endpoint without silently handling failure', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('', { status: 503 }));
    await expect(createApi('/portal', async () => 'token').list('models')).rejects.toThrow(
      'HTTP 503',
    );
    expect(fetchMock).toHaveBeenCalledWith(
      '/portal/models',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    );
    fetchMock.mockRestore();
  });

  it('offers the same unique aliases in the price editor without a wildcard', async () => {
    const models = await createDemoApi().list('models');
    render(
      <FluentProvider theme={webLightTheme}>
        <RecordEditor
          collection="prices"
          policies={[]}
          models={models}
          onSave={vi.fn()}
          onClose={vi.fn()}
        />
      </FluentProvider>,
    );
    const field = screen.getByLabelText(/Model or deployment/);
    const list = document.getElementById(field.getAttribute('list')!)!;
    expect(list.querySelectorAll('option[value="sample-model"]')).toHaveLength(1);
    expect(list.querySelector('option[value="*"]')).toBeNull();
  });
});
