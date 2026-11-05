import type { Collections, Collection, EditableCollection, PortalApi } from './contracts';

export function createDemoApi(): PortalApi {
  const data: { [K in Collection]: Collections[K][] } = {
    policies: [
      {
        id: 'foundry-monthly',
        name: 'Research · monthly AI budget',
        service: 'foundry',
        model: '*',
        tenant_id: 'demo-tenant',
        principal_id: '*',
        limit: 250_000_000,
        period: 'month',
        metric: 'cost',
        enabled: true,
        priority: 10,
      },
      {
        id: 'document-daily',
        name: 'Document processing · daily pages',
        service: 'document-intelligence',
        model: '*',
        tenant_id: 'demo-tenant',
        principal_id: '*',
        limit: 2000,
        period: 'day',
        metric: 'pages',
        enabled: true,
        priority: 20,
      },
      {
        id: 'language-hourly',
        name: 'Language · hourly text records',
        service: 'language',
        model: '*',
        tenant_id: 'demo-tenant',
        principal_id: '*',
        limit: 10000,
        period: 'hour',
        metric: 'text_records',
        enabled: true,
        priority: 30,
      },
    ],
    prices: [
      {
        id: 'sample-price-v1',
        service: 'foundry',
        model: 'sample-model',
        version: 'sample-v1',
        input_per_million: '2.50',
        output_per_million: '10.00',
        cached_input_per_million: '1.25',
        per_page: '0',
        per_text_record: '0',
        per_request: '0',
      },
    ],
    assignments: [
      {
        id: 'research',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        policy_ids: ['foundry-monthly', 'document-daily', 'language-hourly'],
      },
    ],
    usage: [
      {
        id: 'sample-reservation-1',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'reservation',
        timestamp: '2026-01-14T11:24:00Z',
        data: {
          request: {
            service: 'foundry',
            model: 'sample-model',
            streaming: true,
            usage: {
              input_tokens: 12000,
              output_tokens: 4000,
              cached_input_tokens: 0,
            },
          },
          debits: [
            {
              policy_id: 'foundry-monthly',
              metric: 'cost',
              amount: 70000,
              limit: 250000000,
              reset_at: '2026-02-01T00:00:00Z',
            },
          ],
          remaining: 182300000,
          estimated: true,
          status: 'conservative',
        },
      },
      {
        id: 'sample-denial-1',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'denial',
        timestamp: '2026-01-14T11:20:00Z',
        data: {
          request: {
            service: 'document-intelligence',
            model: 'prebuilt-layout',
          },
          allowed: false,
          reason: 'Daily page limit exceeded',
          remaining: 0,
          estimated: false,
        },
      },
      {
        id: 'sample-actual-1',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'settlement',
        timestamp: '2026-01-14T11:18:00Z',
        data: {
          request: {
            service: 'language',
            model: 'sentiment',
            usage: { text_records: 42, requests: 1 },
          },
          remaining: 9958,
          estimated: false,
          status: 'actual',
        },
      },
    ],
    audit: [
      {
        id: 'sample-audit-1',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-admin',
        kind: 'configuration',
        timestamp: '2026-01-14T10:00:00Z',
        data: {
          action: 'save',
          collection: 'policies',
          record_id: 'foundry-monthly',
          actor_id: 'demo-admin',
        },
      },
    ],
    reconciliation: [
      {
        id: 'sample-reconcile-1',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'reconciliation',
        timestamp: '2026-01-14T11:24:00Z',
        data: {
          status: 'awaiting trusted usage',
          reservation_id: 'sample-reservation-1',
          estimated: true,
        },
      },
    ],
  };
  return {
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      return structuredClone(data[collection]);
    },
    async save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void> {
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
