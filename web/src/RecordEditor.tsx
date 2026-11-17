import { useState } from 'react';
import {
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Select,
  Spinner,
} from '@fluentui/react-components';
import type {
  Assignment,
  Budget,
  EditableCollection,
  EditableRecord,
  Model,
  Organization,
  Price,
} from './contracts';
import { track } from './telemetry';

type Draft = Record<string, string | boolean | number>;
const titles: Record<EditableCollection, string> = {
  budgets: 'monthly budget',
  organizations: 'organization unit',
  assignments: 'user assignment',
  prices: 'OpenAI price card',
};
const priceFields = [
  ['input_per_million', 'Uncached input · USD per million tokens'],
  ['cached_input_per_million', 'Cached input · USD per million tokens'],
  ['output_per_million', 'Output · USD per million tokens'],
] as const;
const cacheWriteField = [
  'cache_write_per_million',
  'Cache write · USD per million tokens (optional; blank uses the uncached input rate)',
] as const;
const decimal = /^(0|[1-9]\d*)(\.\d{1,12})?$/;

/** Convert stored integer micro-USD into editable decimal dollars without binary rounding. */
function decimalUsdFromMicros(value: number): string {
  const micros = BigInt(value);
  const whole = micros / 1_000_000n;
  const fractional = (micros % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '');
  return fractional ? `${whole}.${fractional}` : `${whole}`;
}

/** Accept at most six fractional USD digits and reject values beyond safe integer micro-USD. */
function microUsdFromDecimal(value: string): number {
  if (!/^(0|[1-9]\d*)(\.\d{1,6})?$/.test(value))
    throw new Error('Monthly budget must be a non-negative USD amount with up to 6 decimals.');
  const [whole, fraction = ''] = value.split('.');
  const micros = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
  if (micros > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error('Monthly budget is too large to represent safely.');
  return Number(micros);
}

/** Keep form dollars separate from the API budget's micro-USD field until validated submission. */
function initialDraft(collection: EditableCollection, record?: EditableRecord): Draft {
  if (record) {
    const draft: Draft = { ...record };
    if ('limit_micro_usd' in record)
      draft.monthly_usd = decimalUsdFromMicros(record.limit_micro_usd);
    return draft;
  }
  if (collection === 'budgets')
    return {
      id: '',
      tenant_id: '',
      name: '',
      subject_type: 'user',
      subject_id: '',
      model: '*',
      monthly_usd: '',
      enabled: true,
    };
  if (collection === 'organizations')
    return {
      id: '',
      tenant_id: '',
      kind: 'department',
      name: '',
      department_id: '',
      business_unit: '',
      cost_center: '',
      enabled: true,
    };
  if (collection === 'assignments')
    return {
      id: '',
      tenant_id: '',
      principal_id: '',
      team_id: '',
      department_id: '',
      display_label: '',
      enabled: true,
    };
  return {
    id: '',
    model: '',
    version: '',
    input_per_million: '0',
    cached_input_per_million: '0',
    output_per_million: '0',
  };
}

/**
 * Build the collection-specific PUT body from trimmed input and currently loaded relationships.
 * These usability checks do not replace the API's validation or tenant/role enforcement.
 */
function parseDraft(
  collection: EditableCollection,
  draft: Draft,
  organizations: Organization[],
  assignments: Assignment[],
): EditableRecord {
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
  const enabled = Boolean(draft.enabled);

  if (collection === 'budgets') {
    const subject_type = str('subject_type') as Budget['subject_type'];
    const tenant_id = required('tenant_id', 'Tenant ID');
    const subject_id = required('subject_id', 'Budget subject');
    const model = required('model', 'Model');
    if (
      subject_type === 'user' &&
      !assignments.some(
        (assignment) =>
          assignment.principal_id === subject_id &&
          assignment.tenant_id === tenant_id &&
          assignment.enabled,
      )
    )
      throw new Error('Choose a user with an enabled explicit assignment.');
    if (
      subject_type === 'team' &&
      !organizations.some(
        (organization) =>
          organization.id === subject_id &&
          organization.tenant_id === tenant_id &&
          organization.kind === 'team' &&
          organization.enabled,
      )
    )
      throw new Error('Choose an enabled team.');
    if (
      subject_type === 'department' &&
      !organizations.some(
        (organization) =>
          organization.id === subject_id &&
          organization.tenant_id === tenant_id &&
          organization.kind === 'department' &&
          organization.enabled,
      )
    )
      throw new Error('Choose an enabled department.');
    return {
      id,
      tenant_id,
      name: required('name', 'Name'),
      subject_type,
      subject_id,
      model,
      limit_micro_usd: microUsdFromDecimal(str('monthly_usd')),
      enabled,
    };
  }
  if (collection === 'organizations') {
    const kind = str('kind') as Organization['kind'];
    const organization: Organization = {
      id,
      tenant_id: required('tenant_id', 'Tenant ID'),
      kind,
      name: required('name', 'Name'),
      business_unit: required('business_unit', 'Business unit'),
      cost_center: required('cost_center', 'Cost center'),
      enabled,
    };
    if (kind === 'team') {
      const department_id = required('department_id', 'Parent department');
      if (
        !organizations.some(
          (item) =>
            item.id === department_id &&
            item.kind === 'department' &&
            item.tenant_id === organization.tenant_id &&
            item.enabled,
        )
      )
        throw new Error('Choose an enabled department in the same tenant.');
      organization.department_id = department_id;
    }
    return organization;
  }
  if (collection === 'assignments') {
    const team_id = required('team_id', 'Team');
    const team = organizations.find(
      (organization) =>
        organization.id === team_id &&
        organization.tenant_id === str('tenant_id') &&
        organization.kind === 'team' &&
        organization.enabled,
    );
    if (!team?.department_id) throw new Error('Choose an enabled team with a parent department.');
    // Department follows the enabled team in the same tenant, not a separately editable value.
    const assignment: Assignment = {
      id,
      tenant_id: required('tenant_id', 'Tenant ID'),
      principal_id: required('principal_id', 'Entra principal ID'),
      team_id,
      department_id: team.department_id,
      enabled,
    };
    const display_label = str('display_label');
    if (display_label) assignment.display_label = display_label;
    return assignment;
  }
  // Price rates retain decimal strings (up to 12 places); they are not budget micro-USD.
  const validatePrice = (key: string, label: string) => {
    const value = str(key);
    if (!decimal.test(value))
      throw new Error(`${label} must be a non-negative decimal USD amount.`);
    return value;
  };
  const price = {
    id,
    model: required('model', 'Model'),
    version: required('version', 'Version'),
    ...Object.fromEntries(priceFields.map(([key, label]) => [key, validatePrice(key, label)])),
  } as Price;
  if (str(cacheWriteField[0])) price.cache_write_per_million = validatePrice(...cacheWriteField);
  return price;
}

/** Collection-aware form with exact monetary conversion and API-backed save confirmation. */
export function RecordEditor({
  collection,
  record,
  organizations,
  assignments,
  models,
  onSave,
  onClose,
}: {
  collection: EditableCollection;
  record?: EditableRecord;
  organizations: Organization[];
  assignments: Assignment[];
  models: Model[];
  onSave: (record: EditableRecord) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() => initialDraft(collection, record));
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const update = (key: string, value: string | boolean) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  const input = (key: string, label: string, hint?: string, disabled = false) => (
    <Field key={key} label={label} hint={hint} required>
      <Input
        value={String(draft[key] ?? '')}
        disabled={disabled || saving}
        onChange={(_, data) => update(key, data.value)}
        autoComplete="off"
      />
    </Field>
  );
  const select = (key: string, label: string, choices: [string, string][]) => (
    <Field key={key} label={label} required>
      <Select
        value={String(draft[key] ?? '')}
        disabled={saving}
        onChange={(_, data) => update(key, data.value)}
      >
        {choices.map(([value, name]) => (
          <option value={value} key={value}>
            {name}
          </option>
        ))}
      </Select>
    </Field>
  );

  /** Separate validation failures from transport failures without exporting record contents. */
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    let errorCategory = 'validation';
    try {
      const parsed = parseDraft(collection, draft, organizations, assignments);
      setSaving(true);
      errorCategory = 'api';
      await onSave(parsed);
      track('portal_configuration', {
        collection,
        action: record ? 'update' : 'create',
        outcome: 'success',
        errorCategory: 'none',
      });
      onClose();
    } catch (cause) {
      track('portal_configuration', {
        collection,
        action: record ? 'update' : 'create',
        outcome: 'failure',
        errorCategory,
      });
      setError(cause instanceof Error ? cause.message : 'The record could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    track('portal_configuration', {
      collection,
      action: record ? 'update' : 'create',
      outcome: 'cancelled',
      errorCategory: 'none',
    });
    onClose();
  }

  const departments = organizations.filter(
    (organization) => organization.kind === 'department' && organization.enabled,
  );
  const teams = organizations.filter(
    (organization) => organization.kind === 'team' && organization.enabled,
  );
  const userAssignments = assignments.filter((assignment) => assignment.enabled);
  const aliases = [...new Set(models.map((model) => model.model))].sort();
  /** Registered aliases plus a leading option; a saved alias missing from inventory stays selectable. */
  const aliasChoices = (leading: [string, string], keepsWildcard: boolean): [string, string][] => {
    const saved = String(draft.model ?? '');
    const missing = saved && (keepsWildcard ? saved !== '*' : true) && !aliases.includes(saved);
    return [
      leading,
      ...aliases.map((alias): [string, string] => [alias, alias]),
      ...(missing ? [[saved, `${saved} (current)`] as [string, string]] : []),
    ];
  };
  const modelChoices = aliasChoices(['*', 'All registered models (*)'], true);
  const priceModelChoices = aliasChoices(['', 'Choose a registered model'], false);
  const currentType = String(draft.subject_type ?? 'user');

  return (
    <Dialog
      open
      onOpenChange={(_, data) => {
        if (!data.open && !saving) cancel();
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
              {error && (
                <MessageBar intent="error" role="alert">
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
              <div className="form-grid">
                {input(
                  'id',
                  'ID',
                  'Stable, unique identifier. Cannot change after creation.',
                  Boolean(record),
                )}
                {collection !== 'prices' &&
                  input('tenant_id', 'Tenant ID', undefined, Boolean(record))}
                {collection === 'budgets' && (
                  <>
                    {input('name', 'Budget name')}
                    {select('subject_type', 'Budget level', [
                      ['user', 'User'],
                      ['team', 'Team'],
                      ['department', 'Department'],
                    ])}
                    {input(
                      'subject_id',
                      currentType === 'user'
                        ? 'Budget subject ID'
                        : currentType === 'team'
                          ? 'Team ID'
                          : 'Department ID',
                      currentType === 'user'
                        ? `Must match an enabled explicit assignment: ${userAssignments.map((item) => item.principal_id).join(', ') || 'none configured'}.`
                        : currentType === 'team'
                          ? `Must match an enabled team: ${teams.map((item) => item.id).join(', ') || 'none configured'}.`
                          : `Must match an enabled department: ${departments.map((item) => item.id).join(', ') || 'none configured'}.`,
                    )}
                    {select('model', 'Model', modelChoices)}
                    {input(
                      'monthly_usd',
                      'Monthly budget (USD)',
                      'Up to six decimal places; converted exactly to integer micro-USD.',
                    )}
                  </>
                )}
                {collection === 'organizations' && (
                  <>
                    {input('name', 'Display name')}
                    {select('kind', 'Organization unit type', [
                      ['department', 'Department'],
                      ['team', 'Team'],
                    ])}
                    {String(draft.kind) === 'team' &&
                      select('department_id', 'Parent department', [
                        ['', 'Choose an enabled department'],
                        ...departments.map((department): [string, string] => [
                          department.id,
                          `${department.name} · ${department.id}`,
                        ]),
                      ])}
                    {input('business_unit', 'Business unit')}
                    {input('cost_center', 'Cost center')}
                  </>
                )}
                {collection === 'assignments' && (
                  <>
                    {input(
                      'principal_id',
                      'Entra principal ID',
                      'Explicitly assign the signed-in user; membership is not inferred from group claims.',
                    )}
                    {input(
                      'team_id',
                      'Team ID',
                      `Must match an enabled team: ${teams.map((item) => item.id).join(', ') || 'none configured'}.`,
                    )}
                    {input('display_label', 'Display label (optional)')}
                    <Field label="Department" hint="Derived from the selected team.">
                      <Input
                        value={teams.find((team) => team.id === draft.team_id)?.department_id ?? ''}
                        readOnly
                        disabled
                      />
                    </Field>
                  </>
                )}
                {collection === 'prices' && (
                  <>
                    {select('model', 'Model alias', priceModelChoices)}
                    {input('version', 'Price version')}
                    {[...priceFields, cacheWriteField].map(([key, label]) =>
                      input(key, label, 'Exact decimal USD string; not micro-USD.'),
                    )}
                  </>
                )}
                {collection !== 'prices' && (
                  <Field className="form-wide">
                    <Checkbox
                      label="Enabled"
                      checked={Boolean(draft.enabled)}
                      disabled={saving}
                      onChange={(_, data) => update('enabled', Boolean(data.checked))}
                    />
                  </Field>
                )}
              </div>
              {collection === 'budgets' && (
                <p className="note">
                  Limits reset each UTC calendar month. Every matching user, team and department
                  budget applies. This is a soft cap: concurrent in-flight requests may overshoot;
                  later requests are denied.
                </p>
              )}
            </DialogContent>
            <DialogActions>
              <Button disabled={saving} onClick={cancel}>
                Cancel
              </Button>
              <Button appearance="primary" type="submit" disabled={saving}>
                {saving ? <Spinner size="tiny" label="Saving…" /> : 'Save changes'}
              </Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
}
