// @vitest-environment node
import { once } from 'node:events';
import { resolve } from 'node:path';
import { request } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { authorityFor, buildConfig } from '../server/runtime-config.mjs';
import { createPortalServer } from '../server/index.mjs';

const valid = {
  AZURE_CLOUD: 'government',
  AZURE_TENANT_ID: '11111111-1111-1111-1111-111111111111',
  WEB_CLIENT_ID: '22222222-2222-2222-2222-222222222222',
  API_AUDIENCE: 'api://33333333-3333-3333-3333-333333333333',
  API_SCOPE: 'api://33333333-3333-3333-3333-333333333333/access_as_user',
  API_BASE_URL: 'https://gateway.example.us/portal',
};
const running: ReturnType<typeof createPortalServer>[] = [];
const instrumentationKey = '44444444-4444-4444-4444-444444444444';
const connectionString = `InstrumentationKey=${instrumentationKey};IngestionEndpoint=https://dc.applicationinsights.us/`;
afterEach(async () => {
  await Promise.all(
    running
      .splice(0)
      .map(
        (server) =>
          new Promise<void>((done, reject) =>
            server.close((error) => (error ? reject(error) : done())),
          ),
      ),
  );
});

describe('public runtime configuration', () => {
  it('selects only allowlisted public settings and the correct sovereign authority', () => {
    const config = buildConfig({
      ...valid,
      SECRET_PASSWORD: 'must-not-leak',
    });
    expect(config.cloud).toBe('government');
    expect(config).not.toHaveProperty('SECRET_PASSWORD');
    expect(authorityFor(config.cloud)).toBe('https://login.microsoftonline.us');
    expect(authorityFor('commercial')).toBe('https://login.microsoftonline.com');
  });
  it('rejects unsupported clouds, common tenants, mismatched scopes and insecure APIs', () => {
    expect(() =>
      buildConfig({
        ...valid,
        AZURE_CLOUD: 'arbitrary-authority.example',
      }),
    ).toThrow();
    expect(() => buildConfig({ ...valid, AZURE_TENANT_ID: 'common' })).toThrow();
    expect(() =>
      buildConfig({
        ...valid,
        API_SCOPE: 'https://graph.microsoft.us/.default',
      }),
    ).toThrow();
    expect(() =>
      buildConfig({
        ...valid,
        API_BASE_URL: 'http://api.example/portal',
      }),
    ).toThrow();
    expect(() =>
      buildConfig({
        ...valid,
        API_BASE_URL: 'https://user:password@api.example/portal',
      }),
    ).toThrow();
    expect(() => buildConfig({ ...valid, AZURE_CLOUD: '' })).toThrow();
  });
  it('requires explicit demo opt-in and never falls back from invalid real configuration', () => {
    expect(() => buildConfig({})).toThrow();
    expect(buildConfig({ WEB_DEMO_MODE: 'true' }).demoMode).toBe(true);
    expect(() => buildConfig({ WEB_DEMO_MODE: 'yes' })).toThrow();
    expect(() => buildConfig({ ...valid, WEB_CLIENT_ID: '' })).toThrow();
  });
  it('publishes the native logout mode without exposing its federation setting', () => {
    expect(buildConfig(valid).platformAuthEnabled).toBe(false);
    const config = buildConfig({
      ...valid,
      WEB_PLATFORM_AUTH_ENABLED: 'true',
      OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID: 'private-workload-setting',
    });
    expect(config.platformAuthEnabled).toBe(true);
    expect(JSON.stringify(config)).not.toContain('private-workload-setting');
    expect(() => buildConfig({ ...valid, WEB_PLATFORM_AUTH_ENABLED: 'yes' })).toThrow();
  });

  it('publishes only instrumentation routing, never authentication or unrelated connection fields', () => {
    const config = buildConfig({
      ...valid,
      APPLICATIONINSIGHTS_CONNECTION_STRING: `${connectionString};Authorization=private-auth;LiveEndpoint=https://private.example/;ApplicationId=private-app`,
    });
    expect(config.appInsights).toEqual({
      connectionString,
      ingestionOrigin: 'https://dc.applicationinsights.us',
    });
    expect(JSON.stringify(config)).not.toContain('private');
  });
  it.each([
    `InstrumentationKey=${instrumentationKey}`,
    `${connectionString};IngestionEndpoint=https://dc.applicationinsights.us/`,
    connectionString.replace('.us/', '.azure.com/'),
    connectionString.replace('.us/', '.us.evil.example/'),
    connectionString.replace('https:', 'http:'),
    connectionString.replace('https://', 'https://user:password@'),
    connectionString.replace('.us/', '.us:8443/'),
    connectionString.replace('.us/', '.us/v2/track'),
    connectionString.replace('.us/', '.us/?private=query'),
    connectionString.replace('.us/', '.us/#private'),
  ])('disables invalid optional telemetry without rejecting the portal: %s', (value) => {
    expect(
      buildConfig({ ...valid, APPLICATIONINSIGHTS_CONNECTION_STRING: value }).appInsights,
    ).toBeUndefined();
  });
  it('accepts regional ingestion only in the explicitly selected cloud', () => {
    const commercial = connectionString.replace(
      'dc.applicationinsights.us',
      'westus-0.in.applicationinsights.azure.com',
    );
    expect(
      buildConfig({
        ...valid,
        AZURE_CLOUD: 'commercial',
        APPLICATIONINSIGHTS_CONNECTION_STRING: commercial,
      }).appInsights,
    ).toBeDefined();
    expect(
      buildConfig({ ...valid, APPLICATIONINSIGHTS_CONNECTION_STRING: commercial }).appInsights,
    ).toBeUndefined();
  });
  it('publishes the same-origin proxy route and never publishes its server-only key', () => {
    const config = buildConfig({
      ...valid,
      WEB_API_PROXY_ENABLED: 'true',
      PORTAL_APIM_SUBSCRIPTION_KEY: 'must-not-be-published',
    });
    expect(config.apiBaseUrl).toBe('/api');
    expect(config.apiProxyEnabled).toBe(true);
    expect(JSON.stringify(config)).not.toContain('must-not-be-published');
    expect(() => buildConfig({ ...valid, WEB_API_PROXY_ENABLED: 'sometimes' })).toThrow(
      'WEB_API_PROXY_ENABLED',
    );
  });
});

describe('production server', () => {
  async function start(
    config = buildConfig(valid),
    logger = vi.fn(),
    root = resolve('.'),
    proxyOptions = {},
  ) {
    const server = createPortalServer(config, root, logger, proxyOptions);
    running.push(server);
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    return (server.address() as AddressInfo).port;
  }
  it('serves no-store runtime config with sovereign-aware CSP and security headers', async () => {
    const port = await start();
    const response = await fetch(`http://127.0.0.1:${port}/config.json`);
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    expect(response.headers.get('content-security-policy')).toContain(
      'https://login.microsoftonline.us',
    );
    expect(response.headers.get('content-security-policy')).not.toContain(
      'login.microsoftonline.com',
    );
    expect(response.headers.get('content-security-policy')).toContain('https://gateway.example.us');
    expect(response.headers.get('content-security-policy')).toContain('https://graph.microsoft.us');
    expect(response.headers.get('content-security-policy')).toContain('blob:');
    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
    expect((await response.json()).apiScope).toBe(valid.API_SCOPE);
  });
  it('blocks traversal and unsupported methods; serves real assets and SPA paths', async () => {
    const port = await start();
    const status = await new Promise((resolveStatus) => {
      request({ host: '127.0.0.1', port, path: '/%2e%2e/package.json' }, (response) => {
        response.resume();
        resolveStatus(response.statusCode);
      }).end();
    });
    expect(status).toBe(400);
    expect(
      (
        await fetch(`http://127.0.0.1:${port}/config.json`, {
          method: 'POST',
        })
      ).status,
    ).toBe(405);
    const asset = await fetch(`http://127.0.0.1:${port}/index.html`);
    expect(asset.status).toBe(200);
    expect(asset.headers.get('content-type')).toContain('text/html');
    const spa = await fetch(`http://127.0.0.1:${port}/budget-policies`, {
      headers: { Accept: 'text/html' },
    });
    expect(spa.status).toBe(200);
    expect((await fetch(`http://127.0.0.1:${port}/missing.js`)).status).toBe(404);
  });
  it('permits only the validated ingestion origin in CSP, not public-config origin spoofing', async () => {
    const config = buildConfig({
      ...valid,
      APPLICATIONINSIGHTS_CONNECTION_STRING: connectionString,
    });
    config.appInsights!.ingestionOrigin = 'https://evil.example/*';
    const port = await start(config);
    const response = await fetch(`http://127.0.0.1:${port}/config.json`);
    const csp = response.headers.get('content-security-policy')!;
    expect(csp).toContain('https://dc.applicationinsights.us');
    expect(csp).not.toMatch(/evil\.example|\*/);
  });
  it('logs one bounded outcome per request without raw paths, query, headers or identity', async () => {
    const logger = vi.fn();
    const port = await start(buildConfig(valid), logger);
    const response = await fetch(`http://127.0.0.1:${port}/config.json?private-email=x`, {
      headers: { Authorization: 'Bearer private-token', 'X-Correlation-ID': 'private-injected' },
    });
    expect(response.headers.get('X-Correlation-ID')).toMatch(/^[0-9a-f-]{36}$/);
    await response.text();
    await fetch(`http://127.0.0.1:${port}/private-missing.js?private-query`);
    await fetch(`http://127.0.0.1:${port}/private-path`, { method: 'POST' });
    await fetch(`http://127.0.0.1:${port}/%FF`);
    expect(logger).toHaveBeenCalledTimes(4);
    expect(
      logger.mock.calls.map(([record]) => [record.status, record.route, record.errorCategory]),
    ).toEqual([
      [200, 'runtime_config', 'none'],
      [404, 'asset', 'not_found'],
      [405, 'other', 'method_not_allowed'],
      [400, 'other', 'invalid_path'],
    ]);
    for (const [record] of logger.mock.calls) {
      expect(record.durationMs).toBeGreaterThanOrEqual(0);
      expect(record.correlationId).toMatch(/^[0-9a-f-]{36}$/);
    }
    expect(logger.mock.calls[0][0].correlationId).toBe(response.headers.get('X-Correlation-ID'));
    expect(new Set(logger.mock.calls.map(([record]) => record.correlationId)).size).toBe(4);
    expect(JSON.stringify(logger.mock.calls)).not.toMatch(/private|Authorization|config\.json/);
  });
  it('reports safe server error categories and ignores a broken log sink', async () => {
    const logger = vi.fn();
    const port = await start(buildConfig(valid), logger, resolve('missing-static-root'));
    expect(
      (await fetch(`http://127.0.0.1:${port}/private-url`, { headers: { Accept: 'text/html' } }))
        .status,
    ).toBe(500);
    expect(logger).toHaveBeenCalledWith(
      expect.objectContaining({ status: 500, errorCategory: 'serve_error' }),
    );
    expect(JSON.stringify(logger.mock.calls)).not.toContain('private-url');
    const broken = vi.fn().mockImplementation(() => {
      throw new Error('unavailable');
    });
    const healthyPort = await start(buildConfig(valid), broken);
    expect(
      (await fetch(`http://127.0.0.1:${healthyPort}/config.json`, { method: 'HEAD' })).status,
    ).toBe(200);
  });

  it('forwards only allowlisted API requests with the user token and server key', async () => {
    const config = buildConfig({ ...valid, WEB_API_PROXY_ENABLED: 'true' });
    const upstream = vi
      .fn()
      .mockResolvedValueOnce(
        new Response('[{"id":"policy-1"}]', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const logger = vi.fn();
    const port = await start(config, logger, resolve('.'), {
      upstreamUrl: valid.API_BASE_URL,
      subscriptionKey: 'server-private-key',
      fetchImpl: upstream,
    });
    const correlationId = '55555555-5555-5555-5555-555555555555';
    const response = await fetch(`http://127.0.0.1:${port}/api/policies`, {
      headers: {
        'X-Portal-Access-Token': 'header.payload.signature',
        Authorization: 'Bearer platform-or-client-token',
        Cookie: 'AppServiceAuthSession=private-cookie',
        'X-MS-CLIENT-PRINCIPAL': 'private-platform-identity',
        'Ocp-Apim-Subscription-Key': 'client-supplied-key',
        'X-Correlation-ID': correlationId,
      },
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: 'policy-1' }]);
    expect(upstream).toHaveBeenCalledOnce();
    const [target, init] = upstream.mock.calls[0];
    expect(target.href).toBe('https://gateway.example.us/portal/policies');
    expect(init).toMatchObject({ method: 'GET', redirect: 'manual' });
    expect(init.headers).toEqual({
      Authorization: 'Bearer header.payload.signature',
      'Ocp-Apim-Subscription-Key': 'server-private-key',
      'X-Correlation-ID': correlationId,
    });
    expect(JSON.stringify(logger.mock.calls)).not.toMatch(
      /private|signature|platform-or-client-token|client-supplied-key/,
    );
    const mutation = await fetch(`http://127.0.0.1:${port}/api/policies/policy-1`, {
      method: 'PUT',
      headers: {
        'X-Portal-Access-Token': 'header.payload.signature',
        'Content-Type': 'application/json',
        'X-Correlation-ID': correlationId,
        'Ocp-Apim-Subscription-Key': 'another-client-key',
      },
      body: '{"id":"policy-1"}',
    });
    expect(mutation.status).toBe(204);
    const [mutationTarget, mutationInit] = upstream.mock.calls[1];
    expect(mutationTarget.href).toBe('https://gateway.example.us/portal/policies/policy-1');
    expect(mutationInit).toMatchObject({
      method: 'PUT',
      body: '{"id":"policy-1"}',
      redirect: 'manual',
    });
    expect(mutationInit.headers).toEqual({
      Authorization: 'Bearer header.payload.signature',
      'Ocp-Apim-Subscription-Key': 'server-private-key',
      'Content-Type': 'application/json',
      'X-Correlation-ID': correlationId,
    });
    expect(JSON.stringify(logger.mock.calls)).not.toMatch(/private|signature|another-client-key/);
    const publicResponse = await fetch(`http://127.0.0.1:${port}/config.json`);
    expect(await publicResponse.text()).not.toContain('server-private-key');
  });

  it('allows only dashboard period queries and bounds dashboard responses separately', async () => {
    const config = buildConfig({ ...valid, WEB_API_PROXY_ENABLED: 'true' });
    const oversizedForCollections = JSON.stringify([{ title: 'x'.repeat(2_500_000) }]);
    const upstream = vi.fn().mockResolvedValue(
      new Response(oversizedForCollections, {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': String(Buffer.byteLength(oversizedForCollections)),
        },
      }),
    );
    const port = await start(config, vi.fn(), resolve('.'), {
      upstreamUrl: valid.API_BASE_URL,
      subscriptionKey: 'server-private-key',
      fetchImpl: upstream,
    });
    const headers = { 'X-Portal-Access-Token': 'header.payload.signature' };
    for (const suffix of [
      '',
      '?period=24h&extra=x',
      '?period=all',
      '?period=1h&period=7d',
      '?workspace=attacker',
    ]) {
      expect(
        (await fetch(`http://127.0.0.1:${port}/api/dashboard${suffix}`, { headers })).status,
      ).toBe(404);
    }
    expect(upstream).not.toHaveBeenCalled();
    const timeout = vi.spyOn(AbortSignal, 'timeout');
    const response = await fetch(`http://127.0.0.1:${port}/api/dashboard?period=7d`, { headers });
    expect(response.status).toBe(200);
    expect((await response.text()).length).toBeGreaterThan(2_500_000);
    expect(upstream).toHaveBeenCalledOnce();
    const [target, init] = upstream.mock.calls[0];
    expect(target.href).toBe('https://gateway.example.us/portal/dashboard?period=7d');
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect(timeout).toHaveBeenLastCalledWith(45_000);
  });

  it('fails closed for missing tokens, unsupported routes and missing or unresolved keys', async () => {
    const config = buildConfig({ ...valid, WEB_API_PROXY_ENABLED: 'true' });
    const upstream = vi.fn();
    const port = await start(config, vi.fn(), resolve('.'), {
      upstreamUrl: valid.API_BASE_URL,
      subscriptionKey: 'server-private-key',
      fetchImpl: upstream,
    });
    expect((await fetch(`http://127.0.0.1:${port}/api/policies`)).status).toBe(401);
    expect(
      (
        await fetch(`http://127.0.0.1:${port}/api/policies`, {
          headers: { 'X-Portal-Access-Token': 'not-a-bearer-token' },
        })
      ).status,
    ).toBe(401);
    expect((await fetch(`http://127.0.0.1:${port}/api/unsupported`)).status).toBe(404);
    expect(
      (
        await fetch(`http://127.0.0.1:${port}/api/assignments`, {
          method: 'PUT',
          headers: {
            'X-Portal-Access-Token': 'header.payload.signature',
            'Content-Type': 'application/json',
          },
          body: '{}',
        })
      ).status,
    ).toBe(404);
    expect(upstream).not.toHaveBeenCalled();
    expect(() =>
      createPortalServer(config, resolve('.'), vi.fn(), { upstreamUrl: valid.API_BASE_URL }),
    ).toThrow('subscription key is unavailable');
    expect(() =>
      createPortalServer(config, resolve('.'), vi.fn(), {
        upstreamUrl: valid.API_BASE_URL,
        subscriptionKey: '@Microsoft.KeyVault(SecretUri=unresolved)',
      }),
    ).toThrow('subscription key is unavailable');
  });

  it('blocks upstream redirects and does not return their Location header', async () => {
    const config = buildConfig({ ...valid, WEB_API_PROXY_ENABLED: 'true' });
    const upstream = vi
      .fn()
      .mockResolvedValue(
        new Response(null, { status: 302, headers: { Location: 'https://evil.example/' } }),
      );
    const port = await start(config, vi.fn(), resolve('.'), {
      upstreamUrl: valid.API_BASE_URL,
      subscriptionKey: 'server-private-key',
      fetchImpl: upstream,
    });
    const response = await fetch(`http://127.0.0.1:${port}/api/subscriptions`, {
      headers: { 'X-Portal-Access-Token': 'header.payload.signature' },
    });
    expect(response.status).toBe(502);
    expect(response.headers.get('location')).toBeNull();
    expect(await response.json()).toEqual({
      error: 'The API returned an unsupported redirect.',
    });
  });
});
