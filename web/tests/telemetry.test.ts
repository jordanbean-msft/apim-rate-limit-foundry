import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ITelemetryItem } from '@microsoft/applicationinsights-web';
import type { RuntimeConfig } from '../src/contracts';
import { initializeTelemetry, privacyInitializer, stopTelemetry, track } from '../src/telemetry';

const mocks = vi.hoisted(() => ({
  constructor: vi.fn(),
  load: vi.fn(),
  track: vi.fn(),
  initialize: vi.fn(),
  unload: vi.fn(),
}));
vi.mock('@microsoft/applicationinsights-web', () => ({
  ApplicationInsights: class {
    constructor(options: unknown) {
      mocks.constructor(options);
    }
    loadAppInsights = mocks.load;
    addTelemetryInitializer = mocks.initialize;
    trackEvent = mocks.track;
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
  demoMode: true,
  appInsights: {
    connectionString:
      'InstrumentationKey=11111111-1111-1111-1111-111111111111;IngestionEndpoint=https://dc.applicationinsights.us/',
    ingestionOrigin: 'https://dc.applicationinsights.us',
  },
};
beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  stopTelemetry();
  mocks.load.mockReset();
  mocks.track.mockReset();
});

describe('private manual browser telemetry', () => {
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
    expect(mocks.initialize).toHaveBeenCalledWith(privacyInitializer);
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
        collection: 'policies',
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
      properties: { collection: 'policies', method: 'PUT', outcome: 'success' },
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
