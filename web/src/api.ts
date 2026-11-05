import type { Collection, Collections, EditableCollection, PortalApi } from './contracts';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function createApi(baseUrl: string, getAccessToken: () => Promise<string>): PortalApi {
  async function request(path: string, method = 'GET', body?: unknown): Promise<unknown> {
    const token = await getAccessToken();
    const response = await fetch(`${baseUrl}/${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'omit',
      cache: 'no-store',
    });
    if (!response.ok) {
      const message =
        response.status === 401
          ? 'Your API session has expired. Sign in again.'
          : response.status === 403
            ? 'The API denied access. Check your assigned application role.'
            : `The API could not complete this request (HTTP ${response.status}). Retry or contact your administrator.`;
      throw new ApiError(message, response.status);
    }
    return response.status === 204 ? undefined : response.json();
  }
  return {
    async list<K extends Collection>(collection: K): Promise<Collections[K][]> {
      const records = await request(collection);
      if (!Array.isArray(records))
        throw new ApiError('The API returned an invalid collection response.', 502);
      return records;
    },
    async save<K extends EditableCollection>(collection: K, record: Collections[K]): Promise<void> {
      await request(`${collection}/${encodeURIComponent(record.id)}`, 'PUT', record);
    },
    async remove(collection, id) {
      await request(`${collection}/${encodeURIComponent(id)}`, 'DELETE');
    },
  };
}
