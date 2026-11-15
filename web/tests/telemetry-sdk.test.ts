import {
  ApplicationInsights,
  type ISenderConfig,
  type ITelemetryItem,
} from '@microsoft/applicationinsights-web';
import { describe, expect, it } from 'vitest';
import { privacyInitializer } from '../src/telemetry';

describe('real browser SDK dependency pipeline', () => {
  it('preserves the shared W3C IDs through the real SDK wire serializer using an in-memory transport', () => {
    const items: ITelemetryItem[] = [];
    const payloads: string[] = [];
    const transport: Pick<ISenderConfig, 'alwaysUseXhrOverride' | 'httpXHROverride'> = {
      alwaysUseXhrOverride: true,
      httpXHROverride: {
        sendPOST: (payload, complete) => {
          payloads.push(payload.data as string);
          complete(200, {});
        },
      },
    };
    const sdk = new ApplicationInsights({
      config: {
        connectionString:
          'InstrumentationKey=11111111-1111-1111-1111-111111111111;IngestionEndpoint=https://dc.applicationinsights.us/',
        disableAjaxTracking: true,
        disableFetchTracking: true,
        disableExceptionTracking: true,
        disableCorrelationHeaders: true,
        disableCookiesUsage: true,
        isStorageUseDisabled: true,
        enableSessionStorageBuffer: false,
        loggingLevelConsole: 0,
        ...transport,
        extensionConfig: { AppInsightsCfgSyncPlugin: { syncMode: 0, blkCdnCfg: true } },
        featureOptIn: { SdkStats: { mode: 2 } },
      },
    });
    sdk.addTelemetryInitializer(privacyInitializer);
    sdk.addTelemetryInitializer((item) => {
      items.push(item);
      return true;
    });
    try {
      sdk.loadAppInsights();
      sdk.trackDependencyData({
        id: '1234567890abcdef',
        name: 'budgets',
        duration: 12,
        responseCode: 200,
        success: true,
        properties: {
          method: 'GET',
          traceId: '1234567890abcdef1234567890abcdef',
          token: 'private',
        },
      });
      expect(items).toHaveLength(1);
      expect(items[0].baseData).toMatchObject({
        id: '1234567890abcdef',
        name: 'budgets',
        duration: 12,
        properties: { method: 'GET' },
        data: '',
        target: 'ai-gateway',
      });
      expect(items[0].ext).toEqual({ trace: { traceID: '1234567890abcdef1234567890abcdef' } });
      expect(JSON.stringify(items)).not.toContain('private');
      sdk.flush(false, () => {});
      expect(payloads).toHaveLength(1);
      const envelopes = JSON.parse(payloads[0]);
      expect(envelopes).toHaveLength(1);
      expect(envelopes[0].data.baseType).toBe('RemoteDependencyData');
      expect(envelopes[0].data.baseData.id).toBe('1234567890abcdef');
      expect(envelopes[0].tags['ai.operation.id']).toBe('1234567890abcdef1234567890abcdef');
      expect(envelopes[0].tags['ai.cloud.role']).toBe('ai-budget-portal-browser');
      expect(envelopes[0].tags).not.toHaveProperty('ai.user.id');
      expect(JSON.stringify(envelopes)).not.toContain('private');
    } finally {
      sdk.unload(false);
    }
  });
});
