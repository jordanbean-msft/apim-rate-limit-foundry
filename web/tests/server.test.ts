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
});

describe('production server', () => {
  async function start(config = buildConfig(valid), logger = vi.fn(), root = resolve('.')) {
    const server = createPortalServer(config, root, logger);
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
});
