import type { Collection, Collections, EditableCollection, PortalApi } from './contracts';
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
): PortalApi {
  async function request(
    collection: Collection,
    method = 'GET',
    recordId?: string,
    body?: unknown,
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
    try {
      const token = await getAccessToken();
      errorCategory = 'network';
      const path =
        recordId === undefined ? collection : `${collection}/${encodeURIComponent(recordId)}`;
      requestCount = 1;
      const response = await fetch(`${baseUrl}/${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(correlationId ? { 'X-Correlation-ID': correlationId } : {}),
          ...(body ? { 'Content-Type': 'application/json' } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
        credentials: 'omit',
        cache: 'no-store',
      });
      status = response.status;
      if (!response.ok) {
        errorCategory = 'http';
        const message =
          response.status === 401
            ? 'Your API session has expired. Sign in again.'
            : response.status === 403
              ? 'The API denied access. Check your assigned application role.'
              : `The API could not complete this request (HTTP ${response.status}). Retry or contact your administrator.`;
        throw new ApiError(message, response.status);
      }
      errorCategory = 'invalid_response';
      const result: unknown = response.status === 204 ? undefined : await response.json();
      if (method === 'GET' && !Array.isArray(result))
        throw new ApiError('The API returned an invalid collection response.', 502);
      outcome = 'success';
      errorCategory = 'none';
      return result;
    } finally {
      try {
        telemetry(
          'portal_api',
          { collection, method, correlationId, outcome, errorCategory },
          { status, durationMs: performance.now() - start, requestCount },
        );
      } catch {
        // Injected telemetry sinks are also best-effort.
      }
    }
  }
  return {
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      return (await request(collection)) as Collections[K][];
    },
    async save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void> {
      await request(collection, 'PUT', record.id, record);
    },
    async remove(collection, id) {
      await request(collection, 'DELETE', id);
    },
  };
}
