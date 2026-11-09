import type {
  BudgetStatus,
  ChargebackRow,
  Collection,
  Collections,
  DashboardTile,
  EditableCollection,
  PortalApi,
} from './contracts';
import { track, type Telemetry } from './telemetry';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function createApi(
  baseUrl: string,
  getAccessToken: () => Promise<string>,
  telemetry: Telemetry = track,
  proxyEnabled = false,
): PortalApi {
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
    try {
      const token = await getAccessToken();
      errorCategory = 'network';
      requestCount = 1;
      const response = await fetch(`${baseUrl}/${path}`, {
        method,
        headers: {
          ...(proxyEnabled
            ? { 'X-Portal-Access-Token': token }
            : { Authorization: `Bearer ${token}` }),
          ...(correlationId ? { 'X-Correlation-ID': correlationId } : {}),
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: proxyEnabled ? 'same-origin' : 'omit',
        cache: 'no-store',
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
    async save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void> {
      await request(`${collection}/${encodeURIComponent(record.id)}`, 'PUT', record);
    },
    async remove(collection: EditableCollection, id: string) {
      await request(`${collection}/${encodeURIComponent(id)}`, 'DELETE');
    },
  };
}
