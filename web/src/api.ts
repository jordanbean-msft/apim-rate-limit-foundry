import type {
  BudgetStatus,
  ChargebackRow,
  Collection,
  Collections,
  DashboardTile,
  EditableCollection,
  PortalApi,
} from './contracts';
import { beginDependency, track, type Telemetry } from './telemetry';

/** Safe user-facing HTTP failure; upstream response bodies are deliberately not exposed. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Adapt portal routes to the injected token provider and optional same-origin APIM proxy.
 * Collection responses are checked as arrays, not validated field by field at runtime.
 */
export function createApi(
  baseUrl: string,
  getAccessToken: () => Promise<string>,
  telemetry: Telemetry = track,
  proxyEnabled = false,
): PortalApi {
  /** Send JSON mutations, decode JSON/CSV reads, and record bounded outcome metadata. */
  async function request(
    path: string,
    method = 'GET',
    body?: unknown,
    responseType: 'json' | 'text' = 'json',
    expectArray = false,
  ): Promise<unknown> {
    const start = performance.now();
    let correlationId: string | undefined;
    try {
      correlationId = crypto.randomUUID();
    } catch {
      // Correlation is optional when browser cryptography is unavailable.
    }
    let status = 0;
    let requestCount = 0;
    let errorCategory = 'authentication';
    let outcome = 'failure';
    const resource = path.split(/[/?]/, 1)[0] || 'api';
    let dependency: ReturnType<typeof beginDependency> | undefined;
    try {
      const token = await getAccessToken();
      errorCategory = 'network';
      requestCount = 1;
      dependency = beginDependency(resource, method);
      // The proxy needs the platform session cookie but receives the API token separately.
      // Direct API calls send only the bearer token; neither path follows token-bearing redirects.
      const response = await fetch(`${baseUrl}/${path}`, {
        method,
        headers: {
          ...(proxyEnabled
            ? { 'X-Portal-Access-Token': token }
            : { Authorization: `Bearer ${token}` }),
          ...(correlationId ? { 'X-Correlation-ID': correlationId } : {}),
          ...(dependency.traceparent ? { traceparent: dependency.traceparent } : {}),
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: proxyEnabled ? 'same-origin' : 'omit',
        cache: 'no-store',
        redirect: 'error',
      });
      status = response.status;
      if (!response.ok) {
        errorCategory = 'http';
        const message =
          response.status === 401
            ? 'The API rejected authentication. Reload this browser page to refresh sign-in and configuration. If it persists, contact your administrator.'
            : response.status === 403
              ? 'The API denied access. Check your assigned application role.'
              : `The API could not complete this request (HTTP ${response.status}). Retry or contact your administrator.`;
        throw new ApiError(message, response.status);
      }
      errorCategory = 'invalid_response';
      // DELETE may be bodyless; CSV exports bypass JSON decoding.
      const result: unknown =
        response.status === 204
          ? undefined
          : responseType === 'text'
            ? await response.text()
            : await response.json();
      if (expectArray && !Array.isArray(result))
        throw new ApiError('The API returned an invalid collection response.', 502);
      outcome = 'success';
      errorCategory = 'none';
      return result;
    } finally {
      dependency?.finish(status, outcome === 'success' ? 'success' : 'failure');
      try {
        telemetry(
          'portal_api',
          { collection: resource, method, correlationId, outcome, errorCategory },
          { status, durationMs: performance.now() - start, requestCount },
        );
      } catch {
        // Injected telemetry sinks are also best-effort.
      }
    }
  }

  return {
    async dashboard(period): Promise<DashboardTile[]> {
      return (await request(
        `dashboard?period=${period}`,
        'GET',
        undefined,
        'json',
        true,
      )) as DashboardTile[];
    },
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      return (await request(collection, 'GET', undefined, 'json', true)) as Collections[K][];
    },
    // Live Redis-backed spend is separate from asynchronously persisted usage/chargeback history.
    async budgetStatus() {
      return (await request('budgets/status', 'GET', undefined, 'json', true)) as BudgetStatus[];
    },
    async chargeback(month: string, format: 'json' | 'csv') {
      const path = `chargeback?month=${encodeURIComponent(month)}&format=${format}`;
      const result = await request(
        path,
        'GET',
        undefined,
        format === 'csv' ? 'text' : 'json',
        format === 'json',
      );
      return result as ChargebackRow[] | string;
    },
    // PUT replaces the identified configuration record; the API owns validation and authorization.
    async save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void> {
      await request(`${collection}/${encodeURIComponent(record.id)}`, 'PUT', record);
    },
    async remove(collection: EditableCollection, id: string) {
      await request(`${collection}/${encodeURIComponent(id)}`, 'DELETE');
    },
  };
}
