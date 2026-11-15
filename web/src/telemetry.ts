import { ApplicationInsights } from '@microsoft/applicationinsights-web';
import type { ITelemetryItem } from '@microsoft/applicationinsights-web';
import { publicAppInsights } from '../server/telemetry-config.mjs';
import type { RuntimeConfig } from './contracts';

const collections = [
  'models',
  'budgets',
  'organizations',
  'prices',
  'assignments',
  'usage',
  'budgetStatus',
  'chargeback',
  'dashboard',
];
// Fixed dimensions prevent arbitrary identities, record IDs, URLs, tokens, or error text escaping.
const schema = {
  portal_page: {
    page: [
      'overview',
      'budgets',
      'organizations',
      'assignments',
      'prices',
      'models',
      'usage',
      'chargeback',
      'dashboard',
    ],
    outcome: ['success'],
  },
  portal_api: {
    collection: [...collections],
    method: ['GET', 'PUT', 'DELETE'],
    outcome: ['success', 'failure'],
    errorCategory: ['none', 'authentication', 'http', 'network', 'invalid_response'],
  },
  portal_configuration: {
    collection: ['budgets', 'organizations', 'prices', 'assignments'],
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
  portal_chargeback_export: { format: ['json', 'csv'], outcome: ['success', 'failure'] },
  portal_identity: {
    action: ['token_api', 'token_graph'],
    outcome: ['success', 'failure'],
  },
} as const;
export type TelemetryName = keyof typeof schema;
/** Best-effort event sink; the production adapter allowlists dimensions and numeric bounds. */
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
const traceIdPattern = /^(?!0{32}$)[0-9a-f]{32}$/;
const spanIdPattern = /^(?!0{16}$)[0-9a-f]{16}$/;
const dependencyOperations = [...collections, 'graph_profile', 'graph_photo'] as const;
type DependencyOperation = (typeof dependencyOperations)[number];
type DependencyOutcome = 'success' | 'failure';
type DependencyRecord = {
  operation: DependencyOperation;
  method: 'GET' | 'PUT' | 'DELETE';
  traceId: string;
  spanId: string;
  status: number;
  durationMs: number;
  outcome: DependencyOutcome;
};

/** Rebuild manual dependency envelopes without request URLs, headers, or SDK-added context. */
function safeDependency(data: Record<string, unknown> | undefined) {
  const properties = data?.properties as Record<string, unknown> | undefined;
  const spanId = typeof data?.id === 'string' ? data.id.replace(/\.$/, '') : '';
  if (
    typeof data?.name !== 'string' ||
    !(dependencyOperations as readonly string[]).includes(data.name) ||
    !properties ||
    !['GET', 'PUT', 'DELETE'].includes(String(properties.method)) ||
    !traceIdPattern.test(String(properties.traceId)) ||
    !spanIdPattern.test(spanId) ||
    !Number.isInteger(data.responseCode) ||
    Number(data.responseCode) < 0 ||
    Number(data.responseCode) > 599 ||
    typeof data.duration !== 'number' ||
    !Number.isFinite(data.duration) ||
    data.duration < 0 ||
    data.duration > 86_400_000 ||
    typeof data.success !== 'boolean'
  )
    return undefined;
  return {
    ver: 2,
    id: spanId,
    name: data.name,
    target: data.name.startsWith('graph_') ? 'microsoft-graph' : 'ai-gateway',
    type: 'Fetch',
    data: '',
    duration: data.duration,
    responseCode: data.responseCode as number,
    success: data.success,
    properties: { method: properties.method as string },
  };
}

/** Retain declared enum values, bounded metrics, and optional UUID API correlation only. */
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
  if (item.baseType === 'RemoteDependencyData') {
    const dependency = safeDependency(item.baseData);
    if (!dependency) return false;
    const traceId = item.baseData?.properties.traceId as string;
    item.baseData = dependency;
    item.data = {};
    item.ext = { trace: { traceID: traceId } };
    item.tags = {
      'ai.cloud.role': 'ai-budget-portal-browser',
    } as unknown as ITelemetryItem['tags'];
    return true;
  }
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
let dependencySink: ((record: DependencyRecord) => void) | undefined;
let dispose: (() => void) | undefined;
let configured = '';

/** Emit through the active sink without allowing exporter failures to affect user operations. */
export const track: Telemetry = (name, properties, measurements) => {
  try {
    if (Object.hasOwn(schema, name)) sink?.(name, properties, measurements);
  } catch {
    // Export failures must never change authentication, edits or API results.
  }
};

/** Disable exports and release SDK/listener resources before reconfiguration. */
export function stopTelemetry(): void {
  sink = undefined;
  dependencySink = undefined;
  configured = '';
  try {
    dispose?.();
  } catch {
    // Best-effort SDK cleanup.
  }
  dispose = undefined;
}

/** Enable opt-in browser telemetry only for a validated cloud-specific ingestion endpoint. */
export function initializeTelemetry(config: RuntimeConfig): void {
  const validated = publicAppInsights(config.appInsights?.connectionString, config.cloud);
  if (validated?.connectionString === configured) return;
  stopTelemetry();
  if (!validated) return;
  try {
    // Collect only manual events/dependencies: no automatic URL/header/error capture,
    // identity cookies, persistent buffers, or remote SDK configuration.
    const sdk = new ApplicationInsights({
      config: {
        connectionString: validated.connectionString,
        endpointUrl: `${validated.ingestionOrigin}/v2/track`,
        userOverrideEndpointUrl: `${validated.ingestionOrigin}/v2/track`,
        disableAjaxTracking: true,
        disableFetchTracking: true,
        maxAjaxCallsPerView: -1,
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
    dependencySink = (record) =>
      sdk.trackDependencyData({
        id: record.spanId,
        name: record.operation,
        target: record.operation.startsWith('graph_') ? 'microsoft-graph' : 'ai-gateway',
        type: 'Fetch',
        duration: record.durationMs,
        responseCode: record.status,
        success: record.outcome === 'success',
        properties: { traceId: record.traceId, method: record.method },
      });
    configured = validated.connectionString;
    // Report categories rather than exception messages/stacks, which may contain private data.
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

/**
 * Start a manually named dependency and expose an idempotent finish callback.
 * The API client forwards traceparent only to its configured API; Graph callers keep it local.
 */
export function beginDependency(operation: DependencyOperation, method: string = 'GET') {
  const start = performance.now();
  let traceId = '';
  let spanId = '';
  try {
    const hex = (length: number) =>
      Array.from(crypto.getRandomValues(new Uint8Array(length)), (value) =>
        value.toString(16).padStart(2, '0'),
      ).join('');
    traceId = hex(16);
    spanId = hex(8);
  } catch {
    // Missing browser cryptography must not prevent API access.
  }
  const valid = traceIdPattern.test(traceId) && spanIdPattern.test(spanId);
  let finished = false;
  return {
    traceparent: valid ? `00-${traceId}-${spanId}-01` : undefined,
    finish(status: number, outcome: DependencyOutcome): void {
      if (finished) return;
      finished = true;
      if (!valid || !['GET', 'PUT', 'DELETE'].includes(method)) return;
      try {
        dependencySink?.({
          operation,
          method: method as DependencyRecord['method'],
          traceId,
          spanId,
          status,
          durationMs: performance.now() - start,
          outcome,
        });
      } catch {
        // Dependency export cannot change API or optional profile results.
      }
    },
  };
}

/** Measure only token-acquisition outcome; preserve the original result/error without inspecting it. */
export async function observeIdentity<T>(
  action: 'token_api' | 'token_graph',
  acquire: () => Promise<T>,
): Promise<T> {
  let outcome: DependencyOutcome = 'failure';
  try {
    const value = await acquire();
    outcome = 'success';
    return value;
  } finally {
    track('portal_identity', { action, outcome });
  }
}
