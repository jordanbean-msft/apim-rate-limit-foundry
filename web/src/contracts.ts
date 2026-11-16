/** Public gateway protocols, not provider deployment identifiers. */
export type ApiProtocol = 'openai-chat' | 'openai-responses';
/** API application roles; decoded browser claims are navigation hints, not authorization. */
export type Role = 'RateLimit.Admin' | 'RateLimit.Reader' | 'RateLimit.Gateway';

/** Tenant-owned department or team with chargeback dimensions and an optional parent. */
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

/** Explicit principal-to-team membership; no membership inference from Entra group claims. */
export interface Assignment {
  id: string;
  tenant_id: string;
  principal_id: string;
  team_id: string;
  department_id: string;
  display_label?: string;
  enabled: boolean;
}

/** UTC monthly soft cap in integer micro-USD; "*" matches all registered model aliases. */
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

/** Versioned rates as exact decimal USD strings per million tokens, not integer micro-USD. */
export interface Price {
  id: string;
  model: string;
  version: string;
  input_per_million: string;
  cached_input_per_million: string;
  /** Optional; when absent the API charges cache-write tokens at the uncached input rate. */
  cache_write_per_million?: string;
  output_per_million: string;
}

/** Read-only deployment-managed routing, token ceilings, and pinned accounting price version. */
export interface Model {
  id: string;
  model: string;
  api_protocol: ApiProtocol;
  deployment_name: string;
  price_version: string;
  max_input_tokens: number;
  max_output_tokens: number;
}

/**
 * Current UTC-month spend from live Redis counters, not a sum of durable usage history.
 * Remaining micro-USD may be negative because concurrent requests can overshoot the soft cap.
 */
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

/**
 * Persisted usage event; unknown provider usage stays null rather than becoming zero cost.
 * History is written asynchronously and may lag or permanently miss live-counter updates.
 */
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
  cache_write_tokens?: number | null;
  output_tokens: number | null;
  cost_micro_usd: number | null;
  /** Unknown usage carries an estimated upper-bound charge so budgets still decrement. */
  cost_basis?: 'provider_usage' | 'estimated_upper_bound';
  /** Real counts above the model bounds pinned at admission; still priced as reported. */
  out_of_bounds?: boolean;
  price_version: string;
}

/** Monthly persisted-history aggregate; unknown requests are counted separately from actuals. */
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
  cache_write_tokens?: number | null;
  output_tokens: number | null;
  cost_micro_usd: number | null;
  cost_basis?: string;
  unknown_requests: number;
}

/** Route-to-record map used to preserve the record type of generic collection operations. */
export interface Collections {
  budgets: Budget;
  organizations: Organization;
  assignments: Assignment;
  prices: Price;
  models: Model;
  usage: UsageRecord;
}

export type Collection = keyof Collections;
/** Routing/model inventory and usage history are intentionally not portal-editable. */
export type EditableCollection = 'budgets' | 'organizations' | 'assignments' | 'prices';
export type EditableRecord = Budget | Organization | Assignment | Price;

/** Public /config.json response; never includes APIM subscription keys or access tokens. */
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
/** Query result: row cells align by index with columns; tile errors/truncation are independent. */
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

/** Authenticated API boundary shared by live HTTP access and explicitly selected local fixtures. */
export interface PortalApi {
  dashboard(period: DashboardPeriod): Promise<DashboardTile[]>;
  list<K extends Collection>(collection: K): Promise<Collections[K][]>;
  budgetStatus(): Promise<BudgetStatus[]>;
  chargeback(month: string, format: 'json' | 'csv'): Promise<ChargebackRow[] | string>;
  save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void>;
  remove(collection: EditableCollection, id: string): Promise<void>;
}
