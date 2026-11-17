import type {
  BudgetStatus,
  ChargebackRow,
  Collection,
  Collections,
  DashboardTile,
  EditableCollection,
  PortalApi,
} from '../../src/contracts';

interface DemoFixtures {
  identity: string;
  collections: { [K in Collection]: Collections[K][] };
  budget_spend_micro_usd: Record<string, number>;
  chargeback: ChargebackRow[];
  dashboard: DashboardTile[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Match the live API's array-envelope checks without embedding any fixture records. */
function assertFixtures(value: unknown): asserts value is DemoFixtures {
  if (!isRecord(value)) throw new Error('The demo data file has an invalid format.');
  const records = value.collections;
  const collections: Collection[] = [
    'organizations',
    'assignments',
    'budgets',
    'prices',
    'models',
    'usage',
  ];
  if (
    typeof value.identity !== 'string' ||
    !value.identity.trim() ||
    !isRecord(records) ||
    !collections.every((collection) => Array.isArray(records[collection])) ||
    !isRecord(value.budget_spend_micro_usd) ||
    !Object.values(value.budget_spend_micro_usd).every(
      (spent) => typeof spent === 'number' && Number.isSafeInteger(spent) && spent >= 0,
    ) ||
    !Array.isArray(value.chargeback) ||
    !Array.isArray(value.dashboard)
  ) {
    throw new Error('The demo data file has an invalid format.');
  }
}

/**
 * Test-only API double; never imported by application source.
 * Budget status, chargeback, and dashboard fixtures do not recalculate after edits.
 */
export function createDemoApi(source: unknown, now = new Date()): PortalApi {
  const month = now.toISOString().slice(0, 7);
  const fixtures: unknown = JSON.parse(
    JSON.stringify(source)
      .replaceAll('{{month}}', month)
      .replaceAll('{{timestamp}}', now.toISOString()),
  );
  assertFixtures(fixtures);
  const data = fixtures.collections;
  const status: BudgetStatus[] = data.budgets.map((budget) => {
    const spent = fixtures.budget_spend_micro_usd[budget.id];
    if (spent === undefined) throw new Error(`Demo budget ${budget.id} has no spend fixture.`);
    return {
      budget_id: budget.id,
      name: budget.name,
      subject_type: budget.subject_type,
      subject_id: budget.subject_id,
      model: budget.model,
      limit_micro_usd: budget.limit_micro_usd,
      spent_micro_usd: spent,
      remaining_micro_usd: budget.limit_micro_usd - spent,
      month,
    };
  });

  // Clone boundary values so consumers cannot mutate fixtures outside save/remove operations.
  return {
    async dashboard() {
      return structuredClone(fixtures.dashboard);
    },
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      return structuredClone(data[collection]);
    },
    async budgetStatus() {
      return structuredClone(status);
    },
    async chargeback(requestedMonth, format) {
      const rows = fixtures.chargeback.filter((row) => row.month === requestedMonth);
      if (format === 'json') return structuredClone(rows);
      const headings = Object.keys(rows[0] ?? {}) as (keyof ChargebackRow)[];
      return [
        headings.join(','),
        ...rows.map((row) => headings.map((heading) => JSON.stringify(row[heading])).join(',')),
      ].join('\n');
    },
    async save<K extends EditableCollection>(collection: K, record: Collections[K]) {
      const records = data[collection] as Collections[K][];
      const index = records.findIndex((item) => item.id === record.id);
      if (index < 0) records.push(structuredClone(record));
      else records[index] = structuredClone(record);
    },
    async remove(collection, id) {
      const records = data[collection];
      const index = records.findIndex((record) => record.id === id);
      if (index >= 0) records.splice(index, 1);
    },
  };
}
