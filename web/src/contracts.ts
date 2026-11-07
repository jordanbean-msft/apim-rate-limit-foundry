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
  subscription_id: string;
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

export interface Model {
  id: string;
  model: string;
  api_protocol: ApiProtocol;
  deployment_name: string;
  price_version: string;
  max_input_tokens: number;
  max_output_tokens: number;
}

export interface Assignment {
  id: string;
  tenant_id: string;
  subscription_id: string;
  policy_ids: string[];
  reader_principal_ids: string[];
  display_label?: string | null;
}

export interface ApplicationSubscription {
  id: string;
  tenant_id: string;
  display_name: string;
}

export interface CallerUsage {
  id: string;
  tenant_id: string;
  subscription_id: string;
  caller_ref: string;
  display_label: string | null;
  service: Service;
  model: string;
  api_protocol: ApiProtocol | null;
  streaming: boolean;
  period: 'hour' | 'day';
  start_at: string;
  end_at: string;
  request_count: number;
  admitted_requests: number;
  denied_requests: number;
  denied_policy_counts: Record<string, number>;
  estimated_requests: number;
  cost_micro_usd: number;
  actual_cost_micro_usd: number;
  conservative_cost_micro_usd: number;
}

export interface LedgerRecord {
  id: string;
  tenant_id: string;
  subscription_id?: string;
  principal_id?: string;
  kind: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface Collections {
  models: Model;
  subscriptions: ApplicationSubscription;
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
  apiProxyEnabled: boolean;
  demoMode: boolean;
  platformAuthEnabled?: boolean;
  appInsights?: { connectionString: string; ingestionOrigin: string };
}

export type DashboardPeriod = '1h' | '24h' | '7d';
export type DashboardScalar = string | number | boolean | null;
export interface DashboardTile {
  id: string;
  title: string;
  chart: 'Line' | 'Pie' | 'Column' | 'StackedColumn' | '';
  x_axis: string | null;
  y_axis: string | null;
  split_by: string | null;
  columns: { name: string; type: string }[];
  rows: DashboardScalar[][];
  error: string | null;
  truncated: boolean;
}

export interface PortalApi {
  callers(period: 'hour' | 'day'): Promise<CallerUsage[]>;
  dashboard(period: DashboardPeriod): Promise<DashboardTile[]>;
  list<K extends Collection>(collection: K): Promise<Collections[K][]>;
  save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void>;
  remove(collection: EditableCollection, id: string): Promise<void>;
}
