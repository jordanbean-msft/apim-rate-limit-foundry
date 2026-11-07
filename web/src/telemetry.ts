import { ApplicationInsights } from '@microsoft/applicationinsights-web';
import type { ITelemetryItem } from '@microsoft/applicationinsights-web';
import { publicAppInsights } from '../server/telemetry-config.mjs';
import type { RuntimeConfig } from './contracts';

const collections = [
  'models',
  'subscriptions',
  'policies',
  'prices',
  'assignments',
  'usage',
  'audit',
  'reconciliation',
];
const schema = {
  portal_page: { page: ['overview', ...collections, 'denials', 'callers'], outcome: ['success'] },
  portal_api: {
    collection: [...collections, 'callers'],
    method: ['GET', 'PUT', 'DELETE'],
    outcome: ['success', 'failure'],
    errorCategory: ['none', 'authentication', 'http', 'network', 'invalid_response'],
  },
  portal_configuration: {
    collection: ['policies', 'prices', 'assignments'],
    action: ['create', 'update', 'delete'],
    outcome: ['success', 'failure', 'cancelled'],
    errorCategory: ['none', 'validation', 'api'],
  },
  portal_bootstrap: {
    action: ['configuration', 'authentication', 'sign_in', 'sign_out'],
    outcome: ['success', 'failure'],
  },
  portal_refresh: { outcome: ['success', 'partial_failure'] },
  portal_browser_error: { errorCategory: ['script', 'unhandled_rejection', 'render_error'] },
} as const;
export type TelemetryName = keyof typeof schema;
export type Telemetry = (
  name: TelemetryName,
  properties?: Record<string, unknown>,
  measurements?: Record<string, unknown>,
) => void;

const measurementLimits: Partial<Record<TelemetryName, Record<string, number>>> = {
  portal_api: { status: 599, durationMs: 86_400_000, requestCount: 1 },
  portal_refresh: { durationMs: 86_400_000, collectionCount: 8, failureCount: 8 },
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function sanitize(
  name: TelemetryName,
  properties: Record<string, unknown> = {},
  measurements: Record<string, unknown> = {},
) {
  const safeProperties: Record<string, string> = {};
  for (const [key, choices] of Object.entries(schema[name])) {
    const value = properties[key];
    if (typeof value === 'string' && (choices as readonly string[]).includes(value))
      safeProperties[key] = value;
  }
  if (
    name === 'portal_api' &&
    typeof properties.correlationId === 'string' &&
    uuid.test(properties.correlationId)
  )
    safeProperties.correlationId = properties.correlationId;
  const safeMeasurements: Record<string, number> = {};
  for (const [key, limit] of Object.entries(measurementLimits[name] || {})) {
    const value = measurements[key];
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= limit)
      safeMeasurements[key] = Math.round(value);
  }
  return { name, properties: safeProperties, measurements: safeMeasurements };
}

/** Final allowlist runs after SDK context enrichment and before the channel sends it. */
export function privacyInitializer(item: ITelemetryItem): boolean {
  const name: unknown = item.baseData?.name;
  if (item.baseType !== 'EventData' || typeof name !== 'string' || !Object.hasOwn(schema, name))
    return false;
  item.baseData = {
    ver: 2,
    ...sanitize(name as TelemetryName, item.baseData?.properties, item.baseData?.measurements),
  };
  item.data = {};
  item.ext = {};
  item.tags = [];
  return true;
}

let sink: Telemetry | undefined;
let dispose: (() => void) | undefined;
let configured = '';

export const track: Telemetry = (name, properties, measurements) => {
  try {
    if (Object.hasOwn(schema, name)) sink?.(name, properties, measurements);
  } catch {
    // Export failures must never change authentication, edits or API results.
  }
};

export function stopTelemetry(): void {
  sink = undefined;
  configured = '';
  try {
    dispose?.();
  } catch {
    // Best-effort SDK cleanup.
  }
  dispose = undefined;
}

export function initializeTelemetry(config: RuntimeConfig): void {
  const validated = publicAppInsights(config.appInsights?.connectionString, config.cloud);
  if (validated?.connectionString === configured) return;
  stopTelemetry();
  if (!validated) return;
  try {
    const sdk = new ApplicationInsights({
      config: {
        connectionString: validated.connectionString,
        endpointUrl: `${validated.ingestionOrigin}/v2/track`,
        userOverrideEndpointUrl: `${validated.ingestionOrigin}/v2/track`,
        disableAjaxTracking: true,
        disableFetchTracking: true,
        disableExceptionTracking: true,
        enableUnhandledPromiseRejectionTracking: false,
        enableAutoRouteTracking: false,
        enableRequestHeaderTracking: false,
        enableResponseHeaderTracking: false,
        disableCorrelationHeaders: true,
        disableCookiesUsage: true,
        isStorageUseDisabled: true,
        enableSessionStorageBuffer: false,
        enableDebug: false,
        loggingLevelConsole: 0,
        loggingLevelTelemetry: 0,
        disableIkeyDeprecationMessage: true,
        extensionConfig: {
          AppInsightsCfgSyncPlugin: { syncMode: 0, blkCdnCfg: true },
        },
        featureOptIn: { SdkStats: { mode: 2 } },
      },
    });
    dispose = () => {
      sdk.unload(false);
    };
    sdk.addTelemetryInitializer(privacyInitializer);
    sdk.loadAppInsights();
    sink = (name, properties, measurements) =>
      sdk.trackEvent(sanitize(name, properties, measurements));
    configured = validated.connectionString;
    const onError = () => track('portal_browser_error', { errorCategory: 'script' });
    const onRejection = () =>
      track('portal_browser_error', { errorCategory: 'unhandled_rejection' });
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    dispose = () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
      sdk.unload(false);
    };
  } catch {
    stopTelemetry();
  }
}
