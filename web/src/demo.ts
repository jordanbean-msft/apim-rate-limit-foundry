import type {
  BudgetStatus,
  ChargebackRow,
  Collection,
  Collections,
  DashboardTile,
  EditableCollection,
  PortalApi,
} from './contracts';

const month = new Date().toISOString().slice(0, 7);
const organizations: Collections['organizations'][] = [
  {
    id: 'engineering',
    tenant_id: 'demo-tenant',
    kind: 'department',
    name: 'Engineering',
    business_unit: 'Product',
    cost_center: 'CC-4100',
    enabled: true,
  },
  {
    id: 'platform-team',
    tenant_id: 'demo-tenant',
    kind: 'team',
    name: 'Platform',
    department_id: 'engineering',
    business_unit: 'Product',
    cost_center: 'CC-4100',
    enabled: true,
  },
];

export function createDemoApi(): PortalApi {
  const data: { [K in Collection]: Collections[K][] } = {
    organizations,
    assignments: [
      {
        id: 'demo-user-assignment',
        tenant_id: 'demo-tenant',
        principal_id: 'sample-user-reference',
        team_id: 'platform-team',
        department_id: 'engineering',
        display_label: 'Sample user',
        enabled: true,
      },
    ],
    budgets: [
      {
        id: 'engineering-monthly',
        tenant_id: 'demo-tenant',
        name: 'Engineering monthly',
        subject_type: 'department',
        subject_id: 'engineering',
        model: '*',
        limit_micro_usd: 250_000_000,
        enabled: true,
      },
      {
        id: 'platform-monthly',
        tenant_id: 'demo-tenant',
        name: 'Platform monthly',
        subject_type: 'team',
        subject_id: 'platform-team',
        model: '*',
        limit_micro_usd: 100_000_000,
        enabled: true,
      },
      {
        id: 'user-monthly',
        tenant_id: 'demo-tenant',
        name: 'Sample user monthly',
        subject_type: 'user',
        subject_id: 'sample-user-reference',
        model: '*',
        limit_micro_usd: 25_000_000,
        enabled: true,
      },
    ],
    prices: [
      {
        id: 'sample-gpt-4o',
        model: 'gpt-4o',
        version: '2026-01',
        input_per_million: '2.50',
        cached_input_per_million: '1.25',
        output_per_million: '10.00',
      },
      {
        id: 'sample-gpt-4o-mini',
        model: 'gpt-4o-mini',
        version: '2026-01',
        input_per_million: '0.15',
        cached_input_per_million: '0.075',
        output_per_million: '0.60',
      },
    ],
    models: [
      {
        id: 'openai-chat:gpt-4o',
        model: 'gpt-4o',
        api_protocol: 'openai-chat',
        deployment_name: 'provider-chat-standard',
        price_version: '2026-01',
        max_input_tokens: 128000,
        max_output_tokens: 16384,
      },
      {
        id: 'openai-responses:gpt-4o-mini',
        model: 'gpt-4o-mini',
        api_protocol: 'openai-responses',
        deployment_name: 'provider-responses-fast',
        price_version: '2026-01',
        max_input_tokens: 128000,
        max_output_tokens: 16384,
      },
    ],
    usage: [
      {
        event_version: 2,
        event_name: 'usage_recorded',
        event_id: 'event-demo-1',
        request_id: 'request-demo-1',
        timestamp: new Date().toISOString(),
        month,
        tenant_ref: 'tenant-demo-ref',
        user_ref: 'user-demo-ref',
        team_id: 'platform-team',
        department_id: 'engineering',
        business_unit: 'Product',
        cost_center: 'CC-4100',
        subscription_id: 'app-research',
        model: 'gpt-4o',
        api_protocol: 'openai-chat',
        streaming: false,
        status: 'actual',
        input_tokens: 1200,
        cached_input_tokens: 256,
        output_tokens: 200,
        cost_micro_usd: 3180,
        price_version: '2026-01',
      },
      {
        event_version: 2,
        event_name: 'usage_recorded',
        event_id: 'event-demo-2',
        request_id: 'request-demo-2',
        timestamp: new Date().toISOString(),
        month,
        tenant_ref: 'tenant-demo-ref',
        user_ref: 'user-demo-ref',
        team_id: 'platform-team',
        department_id: 'engineering',
        business_unit: 'Product',
        cost_center: 'CC-4100',
        subscription_id: 'app-research',
        model: 'gpt-4o-mini',
        api_protocol: 'openai-responses',
        streaming: true,
        status: 'usage_unknown',
        input_tokens: null,
        cached_input_tokens: null,
        output_tokens: null,
        cost_micro_usd: null,
        price_version: '2026-01',
      },
    ],
  };
  const status: BudgetStatus[] = data.budgets.map((budget, index) => ({
    budget_id: budget.id,
    name: budget.name,
    subject_type: budget.subject_type,
    subject_id: budget.subject_id,
    model: budget.model,
    limit_micro_usd: budget.limit_micro_usd,
    spent_micro_usd: [3_180, 400_000, 900_000][index],
    remaining_micro_usd: budget.limit_micro_usd - [3_180, 400_000, 900_000][index],
    month,
  }));
  const chargeback: ChargebackRow[] = [
    {
      business_unit: 'Product',
      cost_center: 'CC-4100',
      department_id: 'engineering',
      team_id: 'platform-team',
      user_ref: 'user-demo-ref',
      subscription_id: 'app-research',
      model: 'gpt-4o',
      month,
      input_tokens: 1200,
      cached_input_tokens: 256,
      output_tokens: 200,
      cost_micro_usd: 3180,
      unknown_requests: 1,
    },
  ];

  return {
    async dashboard() {
      return structuredClone(dashboardFixtures);
    },
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      return structuredClone(data[collection]);
    },
    async budgetStatus() {
      return structuredClone(status);
    },
    async chargeback(requestedMonth, format) {
      const rows = chargeback.filter((row) => row.month === requestedMonth);
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

const dashboardFixtures: DashboardTile[] = [
  {
    id: 'fixture-spend',
    title: 'Finalized spend over time (fixture)',
    chart: 'Line',
    x_axis: 'Time (UTC)',
    y_axis: 'Cost (USD)',
    split_by: null,
    columns: [
      { name: 'Time', type: 'datetime' },
      { name: 'Cost (USD)', type: 'real' },
    ],
    rows: [
      [`${month}-01T10:00:00Z`, 1.15],
      [`${month}-01T11:00:00Z`, 2.4],
    ],
    error: null,
    truncated: false,
  },
];
