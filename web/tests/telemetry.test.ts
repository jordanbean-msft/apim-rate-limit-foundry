import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ITelemetryItem } from '@microsoft/applicationinsights-web';
import type { RuntimeConfig } from '../src/contracts';
import {
  beginDependency,
  initializeTelemetry,
  observeIdentity,
  privacyInitializer,
  stopTelemetry,
  track,
} from '../src/telemetry';
import { createApi } from '../src/api';

const mocks = vi.hoisted(() => ({
  constructor: vi.fn(),
  load: vi.fn(),
  track: vi.fn(),
  initialize: vi.fn(),
  unload: vi.fn(),
  dependency: vi.fn(),
}));
vi.mock('@microsoft/applicationinsights-web', () => ({
  ApplicationInsights: class {
    constructor(options: unknown) {
      mocks.constructor(options);
    }
    loadAppInsights = mocks.load;
    addTelemetryInitializer = mocks.initialize;
    trackEvent = mocks.track;
    trackDependencyData = mocks.dependency;
    unload = mocks.unload;
  },
}));

const config: RuntimeConfig = {
  cloud: 'government',
  tenantId: '',
  clientId: '',
  apiAudience: '',
  apiScope: '',
  apiBaseUrl: '',
  apiProxyEnabled: false,
  appInsights: {
    connectionString:
      'InstrumentationKey=11111111-1111-1111-1111-111111111111;IngestionEndpoint=https://dc.applicationinsights.us/',
    ingestionOrigin: 'https://dc.applicationinsights.us',
  },
};
beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  stopTelemetry();
  vi.unstubAllGlobals();
  mocks.load.mockReset();
  mocks.track.mockReset();
  mocks.dependency.mockReset();
});

describe('private manual browser telemetry', () => {
  it('joins a manual API dependency to its outgoing W3C header without exporting the path or token', async () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => '11111111-1111-4111-8111-111111111111',
      getRandomValues: (array: Uint8Array) => array.fill(1),
    });
    const fetchImpl = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetchImpl);
    initializeTelemetry(config);
    await createApi('/api', async () => 'private-token', undefined, true).remove(
      'budgets',
      'private-id',
    );
    expect(fetchImpl).toHaveBeenCalledWith(
      '/api/budgets/private-id',
      expect.objectContaining({
        headers: expect.objectContaining({
          traceparent: `00-${'01'.repeat(16)}-${'01'.repeat(8)}-01`,
          'X-Correlation-ID': '11111111-1111-4111-8111-111111111111',
        }),
        redirect: 'error',
      }),
    );
    expect(mocks.dependency).toHaveBeenCalledOnce();
    expect(mocks.dependency).toHaveBeenCalledWith(
      expect.objectContaining({
        id: '01'.repeat(8),
        name: 'budgets',
        target: window.location.origin,
        success: true,
        responseCode: 200,
        properties: { traceId: '01'.repeat(16), method: 'DELETE' },
      }),
    );
    expect(
      JSON.stringify([...mocks.dependency.mock.calls, ...mocks.track.mock.calls]),
    ).not.toContain('private');
  });

  it('records safe dependency failures once and stops exporting after cleanup', async () => {
    initializeTelemetry(config);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private network failure')));
    await expect(
      createApi('/api', async () => 'private-token', undefined, true).list('usage'),
    ).rejects.toThrow();
    expect(mocks.dependency).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: 'usage',
        responseCode: 0,
        success: false,
      }),
    );
    const dependency = beginDependency('graph_photo');
    dependency.finish(404, 'failure');
    dependency.finish(200, 'success');
    expect(mocks.dependency).toHaveBeenCalledTimes(2);
    const afterStop = beginDependency('graph_profile');
    stopTelemetry();
    afterStop.finish(200, 'success');
    expect(mocks.dependency).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(mocks.dependency.mock.calls)).not.toContain('private');
  });

  it('never sends authentication failures as network dependencies or exposes identity errors', async () => {
    initializeTelemetry(config);
    const fail = async () => {
      throw new Error('private auth claims');
    };
    await expect(createApi('/api', fail).list('models')).rejects.toThrow();
    await expect(observeIdentity('token_graph', fail)).rejects.toThrow();
    await expect(observeIdentity('token_api', async () => 'private token')).resolves.toBe(
      'private token',
    );
    expect(mocks.dependency).not.toHaveBeenCalled();
    expect(mocks.track).toHaveBeenCalledWith({
      name: 'portal_identity',
      properties: { action: 'token_graph', outcome: 'failure' },
      measurements: {},
    });
    expect(mocks.track).toHaveBeenLastCalledWith({
      name: 'portal_identity',
      properties: { action: 'token_api', outcome: 'success' },
      measurements: {},
    });
    expect(JSON.stringify(mocks.track.mock.calls)).not.toContain('private');
  });

  it('degrades without cryptography and isolates dependency SDK failures', () => {
    initializeTelemetry(config);
    mocks.dependency.mockImplementationOnce(() => {
      throw new Error('export failed');
    });
    expect(() => beginDependency('models').finish(200, 'success')).not.toThrow();
    vi.stubGlobal('crypto', {
      getRandomValues: () => {
        throw new Error('unavailable');
      },
    });
    const dependency = beginDependency('models');
    expect(dependency.traceparent).toBeUndefined();
    expect(() => dependency.finish(200, 'success')).not.toThrow();
    expect(mocks.dependency).toHaveBeenCalledOnce();
  });

  it('rebuilds manual dependencies after SDK enrichment, preserving only random trace context', () => {
    const dependency: ITelemetryItem = {
      name: 'Microsoft.ApplicationInsights.RemoteDependency',
      baseType: 'RemoteDependencyData',
      baseData: {
        id: '1234567890abcdef.',
        name: 'graph_profile',
        duration: 12,
        responseCode: 200,
        success: true,
        target: 'https://private-url?token=private',
        data: 'private photo',
        properties: {
          method: 'GET',
          traceId: '1234567890abcdef1234567890abcdef',
          user: 'private-user',
        },
      },
      ext: { user: { id: 'private-user' }, trace: { name: 'private-url' } },
      tags: { 'ai.user.id': 'private-user' },
      data: { Authorization: 'private-token' },
    };
    expect(privacyInitializer(dependency)).toBe(true);
    expect(dependency.baseData).toEqual({
      ver: 2,
      id: '1234567890abcdef',
      name: 'graph_profile',
      duration: 12,
      responseCode: 200,
      success: true,
      target: 'https://graph.microsoft.com',
      type: 'Fetch',
      data: '',
      properties: { method: 'GET' },
    });
    expect(dependency.ext).toEqual({ trace: { traceID: '1234567890abcdef1234567890abcdef' } });
    expect(JSON.stringify(dependency)).not.toContain('private');
    for (const change of [
      { name: 'private endpoint' },
      { id: '0'.repeat(16) },
      { duration: Infinity },
      { responseCode: -1 },
      { properties: { traceId: 'private' } },
    ]) {
      expect(
        privacyInitializer({
          name: 'auto',
          baseType: 'RemoteDependencyData',
          baseData: { ...dependency.baseData, ...change },
        }),
      ).toBe(false);
    }
  });

  it('pins the explicit sovereign endpoint and disables every automatic collector and CDN config', () => {
    initializeTelemetry(config);
    initializeTelemetry(config);
    expect(mocks.constructor).toHaveBeenCalledOnce();
    expect(mocks.constructor).toHaveBeenCalledWith({
      config: expect.objectContaining({
        endpointUrl: 'https://dc.applicationinsights.us/v2/track',
        userOverrideEndpointUrl: 'https://dc.applicationinsights.us/v2/track',
        disableAjaxTracking: true,
        disableFetchTracking: true,
        disableExceptionTracking: true,
        enableUnhandledPromiseRejectionTracking: false,
        enableAutoRouteTracking: false,
        enableRequestHeaderTracking: false,
        enableResponseHeaderTracking: false,
        disableCookiesUsage: true,
        isStorageUseDisabled: true,
        enableSessionStorageBuffer: false,
        loggingLevelConsole: 0,
        loggingLevelTelemetry: 0,
        extensionConfig: { AppInsightsCfgSyncPlugin: { syncMode: 0, blkCdnCfg: true } },
      }),
    });
    expect(mocks.initialize).toHaveBeenCalledWith(expect.any(Function));
  });

  it('does not load an SDK or choose a commercial default without a valid explicit endpoint', () => {
    initializeTelemetry({ ...config, appInsights: undefined });
    initializeTelemetry({
      ...config,
      appInsights: {
        connectionString: 'InstrumentationKey=11111111-1111-1111-1111-111111111111',
        ingestionOrigin: 'https://dc.services.visualstudio.com',
      },
    });
    initializeTelemetry({
      ...config,
      appInsights: {
        connectionString: config.appInsights!.connectionString.replace('.us/', '.azure.com/'),
        ingestionOrigin: 'https://dc.applicationinsights.azure.com',
      },
    });
    track('portal_page', { page: 'overview' });
    expect(mocks.constructor).not.toHaveBeenCalled();
    expect(mocks.track).not.toHaveBeenCalled();
  });

  it('allowlists event values and counts, excluding IDs, forms, search, payloads and arbitrary text', () => {
    initializeTelemetry(config);
    track(
      'portal_api',
      {
        collection: 'budgets',
        method: 'PUT',
        outcome: 'success',
        errorCategory: 'private message',
        correlationId: 'private-consumer',
        Authorization: 'private-token',
        url: 'https://api.example/private-id?email=private',
        body: { name: 'private-name' },
      },
      { requestCount: 1, status: 200, durationMs: 5, payload: 1024, identity: 100, price: 3 },
    );
    expect(mocks.track).toHaveBeenCalledWith({
      name: 'portal_api',
      properties: { collection: 'budgets', method: 'PUT', outcome: 'success' },
      measurements: { requestCount: 1, status: 200, durationMs: 5 },
    });
    track(
      'portal_refresh',
      { outcome: 'partial_failure' },
      { durationMs: Infinity, collectionCount: 1e9, failureCount: -1 },
    );
    expect(mocks.track).toHaveBeenLastCalledWith({
      name: 'portal_refresh',
      properties: { outcome: 'partial_failure' },
      measurements: {},
    });
    expect(JSON.stringify(mocks.track.mock.calls)).not.toContain('private');
  });

  it('retains monthly budget configuration telemetry and bounds refresh measurements', () => {
    initializeTelemetry(config);
    track('portal_api', { collection: 'organizations', method: 'GET', outcome: 'success' });
    expect(mocks.track).toHaveBeenLastCalledWith({
      name: 'portal_api',
      properties: { collection: 'organizations', method: 'GET', outcome: 'success' },
      measurements: {},
    });
    track('portal_refresh', { outcome: 'success' }, { collectionCount: 8 });
    expect(mocks.track).toHaveBeenLastCalledWith({
      name: 'portal_refresh',
      properties: { outcome: 'success' },
      measurements: { collectionCount: 8 },
    });
  });

  it('strips SDK-enriched identity, session, operation URL, exception and custom context before export', () => {
    const item: ITelemetryItem = {
      name: 'Microsoft.ApplicationInsights.Event',
      baseType: 'EventData',
      baseData: {
        name: 'portal_page',
        properties: { page: 'overview', url: '/?private-token' },
        measurements: { bodySize: 12 },
        uri: 'private-query',
      },
      tags: { 'ai.user.id': 'private-user', 'ai.operation.name': 'private-url' },
      ext: {
        user: { authId: 'private-id' },
        trace: { name: 'private-url' },
        app: { sesId: 'private-session' },
      },
      data: { Authorization: 'private-token', exception: 'private-message' },
    };
    expect(privacyInitializer(item)).toBe(true);
    expect(item.baseData).toEqual({
      ver: 2,
      name: 'portal_page',
      properties: { page: 'overview' },
      measurements: {},
    });
    expect(item.ext).toEqual({});
    expect(item.tags).toEqual([]);
    expect(item.data).toEqual({});
    expect(JSON.stringify(item)).not.toContain('private');
    for (const baseType of ['ExceptionData', 'PageviewData', 'RemoteDependencyData', 'MessageData'])
      expect(
        privacyInitializer({ name: 'auto', baseType, baseData: { name: 'portal_page' } }),
      ).toBe(false);
    expect(
      privacyInitializer({
        name: 'auto',
        baseType: 'EventData',
        baseData: { name: 'private-custom' },
      }),
    ).toBe(false);
  });

  it('reports fixed browser error categories without touching error messages or rejection reasons', () => {
    initializeTelemetry(config);
    window.dispatchEvent(
      new ErrorEvent('error', { message: 'private prompt', filename: '/private-url?token=secret' }),
    );
    const rejection = new Event('unhandledrejection');
    Object.defineProperty(rejection, 'reason', {
      get: () => {
        throw new Error('must not read');
      },
    });
    window.dispatchEvent(rejection);
    expect(mocks.track).toHaveBeenCalledWith({
      name: 'portal_browser_error',
      properties: { errorCategory: 'script' },
      measurements: {},
    });
    expect(mocks.track).toHaveBeenCalledWith({
      name: 'portal_browser_error',
      properties: { errorCategory: 'unhandled_rejection' },
      measurements: {},
    });
    stopTelemetry();
    mocks.track.mockClear();
    window.dispatchEvent(new ErrorEvent('error', { message: 'private' }));
    expect(mocks.track).not.toHaveBeenCalled();
  });

  it('swallows SDK setup and export failures', () => {
    mocks.load.mockImplementationOnce(() => {
      throw new Error('SDK unavailable');
    });
    expect(() => initializeTelemetry(config)).not.toThrow();
    expect(() => track('portal_page', { page: 'overview' })).not.toThrow();
    initializeTelemetry(config);
    mocks.track.mockImplementationOnce(() => {
      throw new Error('collector blocked');
    });
    expect(() => track('portal_page', { page: 'overview' })).not.toThrow();
  });
});
