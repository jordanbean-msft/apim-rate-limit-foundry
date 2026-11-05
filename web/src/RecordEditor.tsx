import { useState } from 'react';
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Select,
  Spinner,
} from '@fluentui/react-components';
import type { EditableCollection, EditableRecord, Metric, Policy, Service } from './contracts';
import { services } from './format';

type Draft = Record<string, string | boolean>;
const metricChoices: Record<Service, Metric[]> = {
  foundry: ['cost', 'tokens', 'requests'],
  'document-intelligence': ['cost', 'pages', 'requests'],
  language: ['cost', 'text_records', 'requests'],
};
const priceFields = [
  ['input_per_million', 'Input tokens · USD per million'],
  ['output_per_million', 'Output tokens · USD per million'],
  ['cached_input_per_million', 'Cached input tokens · USD per million'],
  ['per_page', 'Pages · USD per page'],
  ['per_text_record', 'Text records · USD per text record'],
  ['per_request', 'Requests · USD per request'],
] as const;
const cacheWritePriceFields = [
  ['cache_write_5m_per_million', 'Cache write · 5 minutes (surcharge rate) · USD per million'],
  ['cache_write_1h_per_million', 'Cache write · 1 hour (surcharge rate) · USD per million'],
] as const;
const decimal = /^(0|[1-9]\d*)(\.\d{1,12})?$/;
const titles = {
  policies: 'policy',
  prices: 'price version',
  assignments: 'assignment',
};

function initialDraft(collection: EditableCollection, record?: EditableRecord): Draft {
  if (record)
    return {
      ...record,
      ...('policy_ids' in record ? { policy_ids: record.policy_ids.join(', ') } : {}),
    } as unknown as Draft;
  const common = { id: '', service: 'foundry', model: '*' };
  if (collection === 'policies')
    return {
      ...common,
      name: '',
      tenant_id: '*',
      principal_id: '*',
      limit: '',
      period: 'month',
      metric: 'cost',
      enabled: true,
      priority: '10',
    };
  if (collection === 'assignments')
    return { id: '', tenant_id: '', principal_id: '', policy_ids: '' };
  return {
    ...common,
    model: '',
    version: '',
    ...Object.fromEntries(priceFields.map(([key]) => [key, '0'])),
    ...Object.fromEntries(cacheWritePriceFields.map(([key]) => [key, ''])),
  };
}

function parseDraft(collection: EditableCollection, draft: Draft): EditableRecord {
  const str = (key: string) => String(draft[key] ?? '').trim();
  const required = (key: string, label: string) => {
    const value = str(key);
    if (!value || value.length > 256)
      throw new Error(`${label} is required and must be at most 256 characters.`);
    return value;
  };
  const id = required('id', 'ID');
  if (!/^[a-zA-Z0-9._-]+$/.test(id))
    throw new Error('ID must contain only letters, numbers, dots, underscores or hyphens.');
  if (collection === 'assignments') {
    const policy_ids = str('policy_ids')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    if (!policy_ids.length || new Set(policy_ids).size !== policy_ids.length)
      throw new Error('Choose at least one policy ID, with no duplicates.');
    const tenant_id = required('tenant_id', 'Tenant ID');
    const principal_id = required('principal_id', 'Principal ID');
    if (tenant_id === '*' || principal_id === '*')
      throw new Error('Assignments require explicit tenant and principal IDs, not wildcards.');
    return { id, tenant_id, principal_id, policy_ids };
  }
  const service = str('service') as Service;
  const model = required('model', 'Model');
  if (collection === 'prices') {
    const validatePrice = (key: string, label: string) => {
      const value = str(key);
      if (!decimal.test(value))
        throw new Error(
          `${label} must be a non-negative decimal USD amount (up to 12 decimal places).`,
        );
      return value;
    };
    const prices = Object.fromEntries(
      priceFields.map(([key, label]) => [key, validatePrice(key, label)]),
    );
    const cacheWritePrices = Object.fromEntries(
      cacheWritePriceFields.map(([key, label]) => [
        key,
        str(key) === '' ? null : validatePrice(key, label),
      ]),
    );
    return {
      id,
      service,
      model,
      version: required('version', 'Version'),
      ...prices,
      ...cacheWritePrices,
    } as EditableRecord;
  }
  const integer = (key: string, label: string, minimum: number) => {
    const value = str(key);
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)) || Number(value) < minimum) {
      throw new Error(`${label} must be a safe whole number of at least ${minimum}.`);
    }
    return Number(value);
  };
  const metric = str('metric') as Metric;
  if (!metricChoices[service].includes(metric))
    throw new Error('Choose a unit supported by this service.');
  return {
    id,
    service,
    model,
    name: required('name', 'Name'),
    tenant_id: str('tenant_id') || '*',
    principal_id: required('principal_id', 'Principal ID'),
    limit: integer('limit', 'Limit', 1),
    priority: integer('priority', 'Priority', 0),
    metric,
    period: str('period') as Policy['period'],
    enabled: Boolean(draft.enabled),
  };
}

export function RecordEditor({
  collection,
  record,
  policies,
  onSave,
  onClose,
}: {
  collection: EditableCollection;
  record?: EditableRecord;
  policies: Policy[];
  onSave: (record: EditableRecord) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(collection, record));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const update = (key: string, value: string | boolean) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  const service = draft.service as Service;
  const input = (key: string, label: string, hint?: string, disabled = false, required = true) => (
    <Field key={key} label={label} hint={hint} required={required}>
      <Input
        value={String(draft[key] ?? '')}
        disabled={disabled || saving}
        onChange={(_, data) => update(key, data.value)}
        autoComplete="off"
      />
    </Field>
  );
  const select = (
    key: string,
    label: string,
    choices: [string, string][],
    onChange?: (value: string) => void,
  ) => (
    <Field key={key} label={label} required>
      <Select
        value={String(draft[key])}
        disabled={saving}
        onChange={(_, data) => (onChange ? onChange(data.value) : update(key, data.value))}
      >
        {choices.map(([value, name]) => (
          <option value={value} key={value}>
            {name}
          </option>
        ))}
      </Select>
    </Field>
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    try {
      const parsed = parseDraft(collection, draft);
      if (
        'policy_ids' in parsed &&
        parsed.policy_ids.some((id) => !policies.some((policy) => policy.id === id))
      ) {
        throw new Error('Every policy ID must exist. Create the policies first.');
      }
      setSaving(true);
      await onSave(parsed);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The record could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(_, data) => {
        if (!data.open && !saving) onClose();
      }}
    >
      <DialogSurface className="editor">
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          noValidate
        >
          <DialogBody>
            <DialogTitle>
              {record ? 'Edit' : 'Create'} {titles[collection]}
            </DialogTitle>
            <DialogContent>
              <p className="muted">
                Changes are enforced by the API. Review units and scope before saving.
              </p>
              {error && (
                <div role="alert" className="error">
                  {error}
                </div>
              )}
              <div className="form-grid">
                {input(
                  'id',
                  'ID',
                  'Stable, unique identifier. Cannot change after creation.',
                  Boolean(record),
                )}
                {collection === 'policies' && input('name', 'Name')}
                {collection !== 'assignments' && (
                  <>
                    {select('service', 'Service', Object.entries(services), (value) => {
                      setDraft((previous) => ({
                        ...previous,
                        service: value,
                        ...(collection === 'policies' ? { metric: 'cost' } : {}),
                      }));
                    })}
                    {input(
                      'model',
                      'Model or deployment',
                      collection === 'policies'
                        ? 'Use * to match all models.'
                        : 'Exact model/deployment ID; matching is enforced by the API.',
                    )}
                  </>
                )}
                {collection === 'policies' && (
                  <>
                    {input(
                      'tenant_id',
                      'Tenant scope',
                      '* means all tenants; prefer an explicit tenant.',
                    )}
                    {input(
                      'principal_id',
                      'Principal scope',
                      '* matches assigned principals; identity is tenant-bound.',
                    )}
                    {select(
                      'metric',
                      'Accounting unit',
                      metricChoices[service].map((value) => [
                        value,
                        value === 'cost' ? 'Cost · integer microUSD' : value.replace('_', ' '),
                      ]),
                    )}
                    {input(
                      'limit',
                      draft.metric === 'cost' ? 'Limit (integer microUSD)' : 'Limit (whole units)',
                      draft.metric === 'cost'
                        ? '1 USD = 1,000,000 microUSD. Example: 25 USD = 25000000.'
                        : 'Positive whole units; tokens include input and output.',
                    )}
                    {select('period', 'UTC period', [
                      ['minute', 'Calendar minute'],
                      ['hour', 'Calendar hour'],
                      ['day', 'Calendar day'],
                      ['month', 'Calendar month'],
                    ])}
                    {input(
                      'priority',
                      'Priority',
                      'Non-negative integer; higher numbers are evaluated first. All matching limits apply.',
                    )}
                    <Checkbox
                      label="Policy enabled"
                      checked={Boolean(draft.enabled)}
                      disabled={saving}
                      onChange={(_, data) => update('enabled', Boolean(data.checked))}
                    />
                  </>
                )}
                {collection === 'prices' && (
                  <>
                    {input(
                      'version',
                      'Version',
                      'Use a new ID/version for new rates; retain versions referenced by history.',
                    )}
                    <div className="form-note">
                      Input price applies to uncached input. Output = generated tokens. Cached input
                      is the discounted cache-read rate. Cache-write rates include the write
                      surcharge: each replaces the uncached rate for its input subset, not an
                      additional charge on total input. Token rates are USD per 1,000,000 tokens;
                      all other rates are USD per single unit. Use 0 for unused standard dimensions,
                      but leave optional cache-write rates blank when unknown or not configured.
                      Unknown is not free: potentially billable cache writes without a known rate
                      fail closed. Sample prices are not live Azure quotes. When more than one
                      version exists for the same service/model, configure the gateway to send
                      price_version; ambiguous versions fail closed.
                    </div>
                    {priceFields.map(([key, label]) =>
                      input(key, label, 'Exact decimal USD string; never microUSD.'),
                    )}
                    {cacheWritePriceFields.map(([key, label]) =>
                      input(
                        key,
                        label,
                        'Required for Anthropic; optional for legacy OpenAI. Full write rate including surcharge. Blank saves null, never an assumed zero.',
                        false,
                        false,
                      ),
                    )}
                  </>
                )}
                {collection === 'assignments' && (
                  <>
                    {input('tenant_id', 'Tenant ID', 'Tenant boundary of the assigned identity.')}
                    {input(
                      'principal_id',
                      'Principal ID',
                      'The server canonical principal key, not an email address.',
                    )}
                    {input('policy_ids', 'Policy IDs', 'Comma-separated existing policy IDs.')}
                    <div className="form-note">
                      Available:{' '}
                      {policies.length
                        ? policies.map((policy) => policy.id).join(', ')
                        : 'No policies. Create a policy first.'}
                    </div>
                  </>
                )}
              </div>
              {collection === 'policies' && (
                <p className="fine-print">
                  Periods use UTC calendar boundaries, not rolling windows. Cost reservations
                  conservatively use the highest applicable known input/cache rate and maximum
                  output; actual settlement can release the difference. Anthropic uses an
                  operator-verified input ceiling, not a universal byte-to-token bound.
                </p>
              )}
            </DialogContent>
            <div className="dialog-actions">
              <Button disabled={saving} onClick={onClose}>
                Cancel
              </Button>
              <Button appearance="primary" type="submit" disabled={saving}>
                {saving ? <Spinner size="tiny" label="Saving…" /> : 'Save changes'}
              </Button>
            </div>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
}
