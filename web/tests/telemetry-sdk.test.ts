import { ApplicationInsights, type ISenderConfig } from '@microsoft/applicationinsights-web';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RuntimeConfig } from '../src/contracts';
import { beginDependency, initializeTelemetry, stopTelemetry } from '../src/telemetry';

const payloads: string[] = [];
const sdks: ApplicationInsights[] = [];

// Keep the production setup and real SDK channel/serializer, replacing only its HTTP transport.
vi.mock('@microsoft/applicationinsights-web', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@microsoft/applicationinsights-web')>();
  return {
    ...actual,
    ApplicationInsights: class extends actual.ApplicationInsights {
      constructor(options: ConstructorParameters<typeof actual.ApplicationInsights>[0]) {
        const transport: Pick<ISenderConfig, 'alwaysUseXhrOverride' | 'httpXHROverride'> = {
          alwaysUseXhrOverride: true,
          httpXHROverride: {
            sendPOST: (payload, complete) => {
              payloads.push(payload.data as string);
              complete(200, {});
            },
          },
        };
        super({
          ...options,
          config: {
            ...options.config,
            ...transport,
          },
        });
        sdks.push(this);
      }
    },
  };
});

function configFor(cloud: RuntimeConfig['cloud'], apiBaseUrl = '/api'): RuntimeConfig {
  return {
    cloud,
    tenantId: '',
    clientId: '',
    apiAudience: '',
    apiScope: '',
    apiBaseUrl,
    apiProxyEnabled: apiBaseUrl === '/api',
    appInsights: {
      connectionString: `InstrumentationKey=11111111-1111-1111-1111-111111111111;IngestionEndpoint=https://dc.applicationinsights.${cloud === 'government' ? 'us' : 'azure.com'}/`,
      ingestionOrigin: '',
    },
  };
}

afterEach(() => {
  stopTelemetry();
  payloads.length = 0;
  sdks.length = 0;
  vi.unstubAllGlobals();
});

describe('real browser SDK dependency pipeline', () => {
  it.each(['government', 'commercial'] as const)(
    'serializes %s Graph and same-origin API targets, preserving W3C IDs without private context',
    (cloud) => {
      vi.stubGlobal('crypto', {
        getRandomValues: (array: Uint8Array) => array.fill(1),
      });
      initializeTelemetry(configFor(cloud));
      sdks.at(-1)!.setAuthenticatedUserContext('private-user', 'private-account', false);
      sdks.at(-1)!.core.getTraceCtx()?.setName('https://private-url?token=secret');
      for (const operation of ['budgets', 'graph_profile', 'graph_photo'] as const) {
        const dependency = beginDependency(operation);
        expect(dependency.traceparent).toBe(`00-${'01'.repeat(16)}-${'01'.repeat(8)}-01`);
        dependency.finish(200, 'success');
      }
      sdks.at(-1)!.flush(false, () => {});
      expect(payloads).toHaveLength(1);
      const envelopes = JSON.parse(payloads[0]);
      expect(envelopes).toHaveLength(3);
      expect(
        envelopes.map((envelope: { data: { baseData: { target: string } } }) => {
          return envelope.data.baseData.target;
        }),
      ).toEqual([
        window.location.host,
        cloud === 'government' ? 'graph.microsoft.us' : 'graph.microsoft.com',
        cloud === 'government' ? 'graph.microsoft.us' : 'graph.microsoft.com',
      ]);
      for (const [index, envelope] of envelopes.entries()) {
        expect(envelope.data.baseType).toBe('RemoteDependencyData');
        expect(envelope.data.baseData).toMatchObject({
          id: '01'.repeat(8),
          name: ['budgets', 'graph_profile', 'graph_photo'][index],
          data: ['budgets', 'graph_profile', 'graph_photo'][index],
          properties: { method: 'GET' },
        });
        expect(envelope.tags['ai.operation.id']).toBe('01'.repeat(16));
        expect(envelope.tags['ai.cloud.role']).toBe('ai-budget-portal-browser');
        expect(envelope.tags).not.toHaveProperty('ai.user.id');
        expect(envelope.tags).not.toHaveProperty('ai.user.authUserId');
        expect(envelope.tags).not.toHaveProperty('ai.operation.name');
      }
      expect(payloads[0]).not.toMatch(
        /private|https?:|Authorization|Bearer|token|ai-gateway|microsoft-graph/,
      );
    },
  );

  it('serializes the configured direct API host and port, never its path', () => {
    const config = configFor('government', 'https://resource.azure-api.us:8443/private-api-path');
    initializeTelemetry(config);
    beginDependency('models').finish(200, 'success');
    sdks.at(-1)!.flush(false, () => {});
    expect(JSON.parse(payloads[0])[0].data.baseData.target).toBe('resource.azure-api.us:8443');
    expect(payloads.join('')).not.toContain('private-api-path');

    // Reconfiguration with the same ingestion endpoint must not retain an old dependency target.
    initializeTelemetry({ ...config, apiBaseUrl: '/api', apiProxyEnabled: true });
    beginDependency('models').finish(200, 'success');
    sdks.at(-1)!.flush(false, () => {});
    expect(JSON.parse(payloads.at(-1)!)[0].data.baseData.target).toBe(window.location.host);
  });

  it.each([
    'https://private-user:private-token@resource.azure-api.us/portal',
    'https://resource.azure-api.us/portal?private-token=secret',
    'https://resource.azure-api.us/portal#private-token',
    'http://resource.azure-api.us/portal',
    'file:///private-path',
  ])('does not export an API dependency for an unsafe configured endpoint: %s', (apiBaseUrl) => {
    initializeTelemetry(configFor('government', apiBaseUrl));
    beginDependency('models').finish(200, 'success');
    sdks.at(-1)!.flush(false, () => {});
    expect(payloads).toHaveLength(0);
  });
});
