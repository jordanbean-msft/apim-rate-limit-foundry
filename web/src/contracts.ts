export type Service = 'foundry' | 'document-intelligence' | 'language';
export type ApiProtocol = 'openai-chat' | 'openai-responses' | 'anthropic-messages';
export type Metric = 'cost' | 'tokens' | 'requests' | 'pages' | 'text_records';
export type Period = 'minute' | 'hour' | 'day' | 'month';
export type Role = 'RateLimit.Admin' | 'RateLimit.Reader' | 'RateLimit.Gateway';

export interface Policy {
  id: string;
  name: string;
  service: Service;
  model: string;
  tenant_id?: string;
  principal_id: string;
  limit: number;
  period: Period;
  metric: Metric;
  enabled: boolean;
  priority: number;
}

export interface Price {
  id: string;
  service: Service;
  model: string;
  version: string;
  input_per_million: string;
  output_per_million: string;
  cached_input_per_million: string;
  cache_write_5m_per_million?: string | null;
  cache_write_1h_per_million?: string | null;
  per_page: string;
  per_text_record: string;
  per_request: string;
}

export interface Assignment {
  id: string;
  tenant_id: string;
  principal_id: string;
  policy_ids: string[];
}

export interface LedgerRecord {
  id: string;
  tenant_id: string;
  principal_id: string;
  kind: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface Collections {
  policies: Policy;
  prices: Price;
  assignments: Assignment;
  usage: LedgerRecord;
  audit: LedgerRecord;
  reconciliation: LedgerRecord;
}
export type Collection = keyof Collections;
export type EditableCollection = 'policies' | 'prices' | 'assignments';
export type EditableRecord = Policy | Price | Assignment;

export interface RuntimeConfig {
  cloud: 'commercial' | 'government';
  tenantId: string;
  clientId: string;
  apiAudience: string;
  apiScope: string;
  apiBaseUrl: string;
  demoMode: boolean;
  appInsights?: { connectionString: string; ingestionOrigin: string };
}

export interface PortalApi {
  list<K extends Collection>(collection: K): Promise<Collections[K][]>;
  save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void>;
  remove(collection: EditableCollection, id: string): Promise<void>;
}
