export type ApiProtocol = 'openai-chat' | 'openai-responses';
export type Role = 'RateLimit.Admin' | 'RateLimit.Reader' | 'RateLimit.Gateway';

export interface Organization {
  id: string;
  tenant_id: string;
  kind: 'team' | 'department';
  name: string;
  department_id?: string;
  business_unit: string;
  cost_center: string;
  enabled: boolean;
}

export interface Assignment {
  id: string;
  tenant_id: string;
  principal_id: string;
  team_id: string;
  department_id: string;
  display_label?: string;
  enabled: boolean;
}

export interface Budget {
  id: string;
  tenant_id: string;
  name: string;
  subject_type: 'user' | 'team' | 'department';
  subject_id: string;
  model: '*' | string;
  limit_micro_usd: number;
  enabled: boolean;
}

export interface Price {
  id: string;
  model: string;
  version: string;
  input_per_million: string;
  cached_input_per_million: string;
  output_per_million: string;
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

export interface BudgetStatus {
  budget_id: string;
  name: string;
  subject_type: 'user' | 'team' | 'department';
  subject_id: string;
  model: string;
  limit_micro_usd: number;
  spent_micro_usd: number;
  remaining_micro_usd: number;
  month: string;
}

export interface UsageRecord {
  event_version: 2;
  event_name: 'usage_recorded';
  event_id: string;
  request_id: string;
  timestamp: string;
  month: string;
  tenant_ref: string;
  user_ref: string;
  team_id: string;
  department_id: string;
  business_unit: string;
  cost_center: string;
  subscription_id: string;
  model: string;
  api_protocol: ApiProtocol;
  streaming: boolean;
  status: 'actual' | 'usage_unknown';
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  cost_micro_usd: number | null;
  price_version: string;
}

export interface ChargebackRow {
  business_unit: string;
  cost_center: string;
  department_id: string;
  team_id: string;
  user_ref: string;
  subscription_id: string;
  model: string;
  month: string;
  input_tokens: number | null;
  cached_input_tokens: number | null;
  output_tokens: number | null;
  cost_micro_usd: number | null;
  unknown_requests: number;
}

export interface Collections {
  budgets: Budget;
  organizations: Organization;
  assignments: Assignment;
  prices: Price;
  models: Model;
  usage: UsageRecord;
}

export type Collection = keyof Collections;
export type EditableCollection = 'budgets' | 'organizations' | 'assignments' | 'prices';
export type EditableRecord = Budget | Organization | Assignment | Price;

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
  dashboard(period: DashboardPeriod): Promise<DashboardTile[]>;
  list<K extends Collection>(collection: K): Promise<Collections[K][]>;
  budgetStatus(): Promise<BudgetStatus[]>;
  chargeback(month: string, format: 'json' | 'csv'): Promise<ChargebackRow[] | string>;
  save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void>;
  remove(collection: EditableCollection, id: string): Promise<void>;
}
