import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApi } from '../src/api';
import { createMsal, tokenRoles } from '../src/auth';

afterEach(() => vi.unstubAllGlobals());

describe('authenticated API', () => {
  it.each([true, false])(
    'clears native sign-in only when App Service authentication is enabled: %s',
    (platformAuthEnabled) => {
      const instance = createMsal({
        cloud: 'government',
        tenantId: '11111111-1111-1111-1111-111111111111',
        clientId: '22222222-2222-2222-2222-222222222222',
        apiAudience: 'api://api',
        apiScope: 'api://api/access_as_user',
        apiBaseUrl: 'https://gateway.example.us/portal',
        apiProxyEnabled: false,
        demoMode: false,
        platformAuthEnabled,
      });
      expect(instance.getConfiguration().auth.postLogoutRedirectUri).toBe(
        window.location.origin + (platformAuthEnabled ? '/.auth/logout' : ''),
      );
      expect(instance.getConfiguration().auth.authority).toBe(
        'https://login.microsoftonline.us/11111111-1111-1111-1111-111111111111',
      );
    },
  );
  it('sends an access token and never an arbitrary consumer principal filter', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('[]'));
    vi.stubGlobal('fetch', fetch);
    const getToken = vi.fn().mockResolvedValue('api-access-token');
    const api = createApi('https://gateway.example/portal', getToken);
    await api.list('usage');
    expect(fetch).toHaveBeenCalledWith(
      'https://gateway.example/portal/usage',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer api-access-token',
          'X-Correlation-ID': expect.stringMatching(/^[0-9a-f-]{36}$/),
        }),
        credentials: 'omit',
      }),
    );
    expect(getToken).toHaveBeenCalledOnce();
  });

  it('requests only the selected dashboard period through the configured API root', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('[]'));
    vi.stubGlobal('fetch', fetch);
    const api = createApi('/api', async () => 'api-access-token', undefined, true);
    await expect(api.dashboard('7d')).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalledWith(
      '/api/dashboard?period=7d',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Portal-Access-Token': 'api-access-token' }),
        credentials: 'same-origin',
      }),
    );
  });

  it('uses the exact monthly budget-status and chargeback API routes and supports CSV bodies', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response('[]'))
      .mockResolvedValueOnce(new Response('[]'))
      .mockResolvedValueOnce(
        new Response('month,cost_micro_usd\n2026-11,1200000', {
          headers: { 'Content-Type': 'text/csv' },
        }),
      );
    vi.stubGlobal('fetch', fetch);
    const api = createApi('/api', async () => 'token', undefined, true);
    await expect(api.budgetStatus()).resolves.toEqual([]);
    await expect(api.chargeback('2026-11', 'json')).resolves.toEqual([]);
    await expect(api.chargeback('2026-11', 'csv')).resolves.toContain('1200000');
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      '/api/budgets/status',
      '/api/chargeback?month=2026-11&format=json',
      '/api/chargeback?month=2026-11&format=csv',
    ]);
  });

  it('surfaces dashboard service failures for the page retry state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));
    await expect(createApi('/api', async () => 'token').dashboard('24h')).rejects.toMatchObject({
      status: 503,
    });
  });

  it('uses the native same-origin proxy header without sending the token as Authorization', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('[]'));
    vi.stubGlobal('fetch', fetch);
    await createApi('/api', async () => 'api-access-token', undefined, true).list('assignments');
    expect(fetch).toHaveBeenCalledWith(
      '/api/assignments',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Portal-Access-Token': 'api-access-token',
        }),
        credentials: 'same-origin',
      }),
    );
    expect(fetch.mock.calls[0][1].headers).not.toHaveProperty('Authorization');
    expect(fetch.mock.calls[0][1].credentials).not.toBe('omit');
  });

  it.each([401, 403, 500])(
    'surfaces HTTP %i failures instead of returning demo records',
    async (status) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })));
      await expect(
        createApi('https://api.example/api', async () => 'token').list('budgets'),
      ).rejects.toMatchObject({ status });
    },
  );

  it.each([true, false])(
    'does not misdiagnose HTTP 401 as session expiry (proxy: %s)',
    async (proxyEnabled) => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response('{"message":"Access denied due to missing subscription key."}', {
            status: 401,
          }),
        ),
      );
      await expect(
        createApi('/api', async () => 'token', undefined, proxyEnabled).list('models'),
      ).rejects.toThrow('Reload this browser page to refresh sign-in and configuration.');
    },
  );

  it.each([200, 204])('supports HTTP %i delete acknowledgments', async (status) => {
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(status === 200 ? '{"deleted":"policy-1"}' : null, { status }),
      );
    vi.stubGlobal('fetch', fetch);
    await expect(
      createApi('https://api.example/api', async () => 'token').remove('budgets', 'budget-1'),
    ).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(
      'https://api.example/api/budgets/budget-1',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });

  it('rejects an invalid collection contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"items":[]}')));
    await expect(
      createApi('https://api.example/api', async () => 'token').list('usage'),
    ).rejects.toThrow('invalid collection response');
  });

  it.each([
    ['http', new Response('{"secret":"response-private"}', { status: 403 })],
    ['invalid_response', new Response('{"secret":"response-private"}')],
    ['invalid_response', new Response('invalid-json-private')],
  ])(
    'logs sanitized %s outcomes without headers, URL or response data',
    async (category, response) => {
      const telemetry = vi.fn();
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
      const api = createApi(
        'https://private.example/api?private-query',
        async () => 'private-token',
        telemetry,
      );
      await expect(api.list('budgets')).rejects.toThrow();
      expect(telemetry).toHaveBeenCalledWith(
        'portal_api',
        expect.objectContaining({
          collection: 'budgets',
          outcome: 'failure',
          errorCategory: category,
        }),
        expect.objectContaining({ requestCount: 1, status: response.status }),
      );
      expect(JSON.stringify(telemetry.mock.calls)).not.toMatch(/private|Authorization|secret/);
    },
  );

  it('logs token and network errors without their messages and preserves the original rejection', async () => {
    for (const category of ['authentication', 'network']) {
      const error = new Error('private token/URL/identity');
      const telemetry = vi.fn();
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error));
      const getToken =
        category === 'authentication'
          ? async () => {
              throw error;
            }
          : async () => 'private-token';
      await expect(
        createApi('https://private.example', getToken, telemetry).list('usage'),
      ).rejects.toBe(error);
      expect(telemetry).toHaveBeenCalledWith(
        'portal_api',
        expect.objectContaining({ errorCategory: category }),
        expect.objectContaining({ status: 0, requestCount: category === 'authentication' ? 0 : 1 }),
      );
      expect(JSON.stringify(telemetry.mock.calls)).not.toContain('private');
    }
  });

  it('logs a successful mutation without its ID or body, even when the telemetry sink throws', async () => {
    const telemetry = vi.fn().mockImplementation(() => {
      throw new Error('sink unavailable');
    });
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetch);
    await expect(
      createApi('https://api.example', async () => 'private-token', telemetry).remove(
        'budgets',
        'private-principal',
      ),
    ).resolves.toBeUndefined();
    expect(telemetry).toHaveBeenCalledWith(
      'portal_api',
      expect.objectContaining({ collection: 'budgets', method: 'DELETE', outcome: 'success' }),
      expect.objectContaining({ status: 204 }),
    );
    expect(JSON.stringify(telemetry.mock.calls)).not.toContain('private');
    const headers = fetch.mock.calls[0][1].headers;
    expect(headers['X-Correlation-ID']).toBe(telemetry.mock.calls[0][1].correlationId);
  });

  it('preserves API access when optional correlation generation fails', async () => {
    vi.spyOn(crypto, 'randomUUID').mockImplementation(() => {
      throw new Error('unavailable');
    });
    const fetch = vi.fn().mockResolvedValue(new Response('[]'));
    vi.stubGlobal('fetch', fetch);
    await expect(
      createApi('https://api.example', async () => 'token').list('usage'),
    ).resolves.toEqual([]);
    expect(fetch.mock.calls[0][1].headers).not.toHaveProperty('X-Correlation-ID');
  });

  it('fails closed when no portal roles are present in an access token', () => {
    const token = (claims: unknown) => `header.${btoa(JSON.stringify(claims))}.signature`;
    expect(tokenRoles(token({ roles: ['RateLimit.Reader', 'unknown'] }))).toEqual([
      'RateLimit.Reader',
    ]);
    expect(tokenRoles(token({}))).toEqual([]);
    expect(tokenRoles('invalid')).toEqual([]);
  });
});
