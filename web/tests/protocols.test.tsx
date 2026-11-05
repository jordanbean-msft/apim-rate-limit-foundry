import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfigurationTable } from '../src/components/ConfigurationTable';
import { LedgerTable } from '../src/components/LedgerTable';
import { Overview } from '../src/components/Overview';
import type { LedgerRecord, Price } from '../src/contracts';
import { createDemoApi } from '../src/demo';
import { RecordEditor } from '../src/RecordEditor';

const legacyPrice: Price = {
  id: 'legacy-openai',
  service: 'foundry',
  model: 'legacy-model',
  version: 'v1',
  input_per_million: '2.50',
  output_per_million: '10.00',
  cached_input_per_million: '1.25',
  per_page: '0',
  per_text_record: '0',
  per_request: '0',
};

function wrap(children: React.ReactNode) {
  return render(<FluentProvider theme={webLightTheme}>{children}</FluentProvider>);
}

describe('optional cache-write prices', () => {
  it('preserves legacy prices without inventing write rates when blank fields save as null', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="prices"
        record={legacyPrice}
        policies={[]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    const write5m = screen.getByLabelText(/Cache write · 5 minutes/);
    const write1h = screen.getByLabelText(/Cache write · 1 hour/);
    expect(write5m).toHaveValue('');
    expect(write5m).not.toBeRequired();
    expect(write1h).toHaveValue('');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        ...legacyPrice,
        cache_write_5m_per_million: null,
        cache_write_1h_per_million: null,
      }),
    );
  });

  it('preserves exact write-rate decimal strings and distinguishes explicit zero from unknown', async () => {
    const user = userEvent.setup();
    const save = vi.fn().mockResolvedValue(undefined);
    wrap(
      <RecordEditor
        collection="prices"
        record={legacyPrice}
        policies={[]}
        onSave={save}
        onClose={vi.fn()}
      />,
    );
    await user.type(screen.getByLabelText(/Cache write · 5 minutes/), '0.000000123456');
    await user.type(screen.getByLabelText(/Cache write · 1 hour/), '0');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          cache_write_5m_per_million: '0.000000123456',
          cache_write_1h_per_million: '0',
        }),
      ),
    );
  });

  it.each(['-1', '1e3', '0.1234567890123'])(
    'rejects invalid optional write rate %s',
    async (value) => {
      const user = userEvent.setup();
      const save = vi.fn();
      wrap(
        <RecordEditor
          collection="prices"
          record={legacyPrice}
          policies={[]}
          onSave={save}
          onClose={vi.fn()}
        />,
      );
      await user.type(screen.getByLabelText(/Cache write · 5 minutes/), value);
      await user.click(screen.getByRole('button', { name: 'Save changes' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('non-negative decimal USD');
      expect(save).not.toHaveBeenCalled();
    },
  );

  it('shows absent and null write rates as not configured, never free', () => {
    wrap(
      <ConfigurationTable
        collection="prices"
        records={[{ ...legacyPrice, cache_write_1h_per_million: null }]}
        admin={false}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(
      screen.getByText('Cache write · 5 minutes / million tokens (includes surcharge)')
        .nextElementSibling,
    ).toHaveTextContent('Not configured');
    expect(
      screen.getByText('Cache write · 1 hour / million tokens (includes surcharge)')
        .nextElementSibling,
    ).toHaveTextContent('Not configured');
    expect(screen.getByText(/Cache read discount \$1.25/)).toBeInTheDocument();
  });
});

describe('protocol-aware event accounting', () => {
  it('renders all three provider formats, legacy chat, and normalized total input without adding cache subsets', async () => {
    const records = await createDemoApi().list('usage');
    wrap(<LedgerTable records={records} mode="usage" />);
    expect(screen.getByText('OpenAI Chat Completions')).toBeInTheDocument();
    expect(screen.getByText('OpenAI Chat Completions (legacy default)')).toBeInTheDocument();
    expect(screen.getByText('OpenAI Responses')).toBeInTheDocument();
    expect(screen.getByText('Anthropic Messages')).toBeInTheDocument();
    const messagesRow = screen.getByText('sample-messages-actual').closest('tr')!;
    const inputLabel = within(messagesRow).getByText(
      'Input tokens (total, includes cache reads/writes)',
    );
    expect(inputLabel.nextElementSibling).toHaveTextContent(/^2000$/);
    expect(
      within(messagesRow).getByText('Cache reads (input subset; discounted rate)')
        .nextElementSibling,
    ).toHaveTextContent(/^500$/);
    expect(
      within(messagesRow).getByText('Cache writes · 5 minutes (input subset; surcharge rate)')
        .nextElementSibling,
    ).toHaveTextContent(/^300$/);
    expect(
      within(messagesRow).getByText('Cache writes · 1 hour (input subset; surcharge rate)')
        .nextElementSibling,
    ).toHaveTextContent(/^200$/);
    expect(within(messagesRow).getByText(/Do not add them again/)).toBeInTheDocument();
    const responsesRow = screen.getByText('sample-responses-actual').closest('tr')!;
    expect(
      within(responsesRow).getByText('Input tokens (total, includes cache reads/writes)')
        .nextElementSibling,
    ).toHaveTextContent(/^2000$/);
    const documentRow = screen.getByText('sample-denial-1').closest('tr')!;
    expect(within(documentRow).queryByText(/OpenAI|Anthropic/)).not.toBeInTheDocument();
  });

  it('reports one event cost and one event count even when multiple budget rules debit that cost', async () => {
    const record = (await createDemoApi().list('usage')).find(
      (item) => item.id === 'sample-messages-actual',
    )!;
    wrap(
      <Overview policies={[]} usage={[record]} errors={{}} loading={false} navigate={vi.fn()} />,
    );
    expect(screen.getByText('Usage events').closest('article')).toHaveTextContent(
      '1Returned by the API',
    );
    expect(screen.getAllByText(/Event cost:/)).toHaveLength(1);
    expect(screen.getByText(/Event cost:/)).toHaveTextContent('$0.008475 (8475 microUSD)');
    expect(screen.queryByText(/\$0\.01695/)).not.toBeInTheDocument();
    expect(screen.getByText(/do not sum matching budget rules/)).toBeInTheDocument();
    expect(screen.getByText(/foundry-monthly:/)).toBeInTheDocument();
    expect(screen.getByText(/foundry-daily:/)).toBeInTheDocument();
  });

  it.each(['conservative', 'actual'])(
    'preserves estimated confidence and unknown cache counters even with status %s',
    (status) => {
      const record: LedgerRecord = {
        id: 'incomplete-message',
        tenant_id: 'tenant',
        principal_id: 'principal',
        kind: 'reservation',
        timestamp: '2026-01-14T11:24:00Z',
        data: {
          request: {
            service: 'foundry',
            model: 'claude',
            usage: { input_tokens: 1200, output_tokens: 300 },
          },
          api_protocol: 'anthropic-messages',
          usage: { input_tokens: 1000, output_tokens: 200 },
          estimated: true,
          status,
          cached_input_reported: false,
          cache_write_input_reported: false,
          reason: 'incomplete_provider_usage',
        },
      };
      wrap(<LedgerTable records={[record]} mode="usage" />);
      expect(screen.getByText('Anthropic Messages')).toBeInTheDocument();
      expect(screen.getByText('Estimated / conservative')).toBeInTheDocument();
      expect(screen.queryByText('Actual')).not.toBeInTheDocument();
      expect(
        screen.getByText('Cache writes · 5 minutes (input subset; surcharge rate)')
          .nextElementSibling,
      ).toHaveTextContent('Not reported');
      expect(
        screen.getByText('Cache writes · 1 hour (input subset; surcharge rate)').nextElementSibling,
      ).toHaveTextContent('Not reported');
      expect(screen.getByText(/Cache-write usage was not reported/)).toBeInTheDocument();
      expect(screen.getByText(/Cache-read usage was not reported/)).toBeInTheDocument();
    },
  );

  it('does not silently reinterpret an unknown protocol as chat', () => {
    const record: LedgerRecord = {
      id: 'unknown',
      tenant_id: 'tenant',
      principal_id: 'principal',
      kind: 'reservation',
      timestamp: '2026-01-14T11:24:00Z',
      data: { request: { service: 'foundry', api_protocol: 'future-format' }, estimated: true },
    };
    wrap(<LedgerTable records={[record]} mode="usage" />);
    expect(screen.getByText('Unrecognized protocol: future-format')).toBeInTheDocument();
    expect(screen.queryByText(/OpenAI Chat/)).not.toBeInTheDocument();
  });
});
