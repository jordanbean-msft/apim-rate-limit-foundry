// @vitest-environment node
import { once } from 'node:events';
import { resolve } from 'node:path';
import { request } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterEach, describe, expect, it } from 'vitest';
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
});

describe('production server', () => {
  async function start() {
    const server = createPortalServer(buildConfig(valid), resolve('.'));
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
});
