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
        id: 'foundry-daily',
        name: 'Research · daily AI budget',
        service: 'foundry',
        model: '*',
        tenant_id: 'demo-tenant',
        principal_id: '*',
        limit: 25_000_000,
        period: 'day',
        metric: 'cost',
        enabled: true,
        priority: 15,
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
      {
        id: 'sample-responses-price-v1',
        service: 'foundry',
        model: 'sample-responses-model',
        version: 'sample-v1',
        input_per_million: '2.00',
        output_per_million: '8.00',
        cached_input_per_million: '1.00',
        per_page: '0',
        per_text_record: '0',
        per_request: '0',
      },
      {
        id: 'sample-messages-price-v1',
        service: 'foundry',
        model: 'sample-claude-model',
        version: 'sample-v1',
        input_per_million: '3.00',
        output_per_million: '15.00',
        cached_input_per_million: '0.30',
        cache_write_5m_per_million: '3.75',
        cache_write_1h_per_million: '6.00',
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
        policy_ids: ['foundry-monthly', 'foundry-daily', 'document-daily', 'language-hourly'],
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
          cost_micro_usd: 70000,
          estimated: true,
          status: 'conservative',
        },
      },
      {
        id: 'sample-responses-actual',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'reservation',
        timestamp: '2026-01-14T11:23:00Z',
        data: {
          request: {
            service: 'foundry',
            api_protocol: 'openai-responses',
            model: 'sample-responses-model',
            streaming: false,
            usage: { input_tokens: 2400, output_tokens: 500, requests: 1 },
          },
          api_protocol: 'openai-responses',
          usage: { input_tokens: 2000, output_tokens: 300, cached_input_tokens: 800, requests: 1 },
          provider_usage: {
            input_tokens: 2000,
            output_tokens: 300,
            input_tokens_details: { cached_tokens: 800 },
          },
          cost_micro_usd: 5600,
          cached_input_reported: true,
          estimated: false,
          status: 'actual',
        },
      },
      {
        id: 'sample-messages-actual',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'reservation',
        timestamp: '2026-01-14T11:22:00Z',
        data: {
          request: {
            service: 'foundry',
            api_protocol: 'anthropic-messages',
            model: 'sample-claude-model',
            streaming: false,
            usage: { input_tokens: 16000, output_tokens: 4000, requests: 1 },
          },
          api_protocol: 'anthropic-messages',
          usage: {
            input_tokens: 2000,
            output_tokens: 200,
            cached_input_tokens: 500,
            cache_write_input_tokens_5m: 300,
            cache_write_input_tokens_1h: 200,
            requests: 1,
          },
          provider_usage: {
            input_tokens: 1000,
            output_tokens: 200,
            cache_read_input_tokens: 500,
            cache_creation_input_tokens: 500,
            cache_creation: { ephemeral_5m_input_tokens: 300, ephemeral_1h_input_tokens: 200 },
          },
          debits: [
            {
              policy_id: 'foundry-monthly',
              metric: 'cost',
              amount: 8475,
              limit: 250000000,
              reset_at: '2026-02-01T00:00:00Z',
            },
            {
              policy_id: 'foundry-daily',
              metric: 'cost',
              amount: 8475,
              limit: 25000000,
              reset_at: '2026-01-15T00:00:00Z',
            },
          ],
          cost_micro_usd: 8475,
          cached_input_reported: true,
          cache_write_input_reported: true,
          estimated: false,
          status: 'actual',
        },
      },
      {
        id: 'sample-chat-actual',
        tenant_id: 'demo-tenant',
        principal_id: 'demo-research-team',
        kind: 'reservation',
        timestamp: '2026-01-14T11:21:00Z',
        data: {
          request: {
            service: 'foundry',
            api_protocol: 'openai-chat',
            model: 'sample-model',
            streaming: false,
            usage: { input_tokens: 1200, output_tokens: 200, requests: 1 },
          },
          api_protocol: 'openai-chat',
          usage: { input_tokens: 1000, output_tokens: 100, cached_input_tokens: 256, requests: 1 },
          provider_usage: {
            prompt_tokens: 1000,
            completion_tokens: 100,
            prompt_tokens_details: { cached_tokens: 256 },
          },
          cost_micro_usd: 3180,
          cached_input_reported: true,
          estimated: false,
          status: 'actual',
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
