import { ROOT_CONTEXT, SpanKind, SpanStatusCode, trace } from '@opentelemetry/api';
import {
  AzureMonitorLogExporter,
  AzureMonitorTraceExporter,
} from '@azure/monitor-opentelemetry-exporter';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { BatchLogRecordProcessor, LoggerProvider } from '@opentelemetry/sdk-logs';
import { BasicTracerProvider, BatchSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { publicAppInsights } from './telemetry-config.mjs';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const traceparent = /^00-([0-9a-f]{32})-([0-9a-f]{16})-(00|01)$/;
const routes = new Set(['other', 'api_proxy', 'runtime_config', 'page', 'asset']);
const categories = new Set([
  'none',
  'connection_closed',
  'invalid_path',
  'proxy_disabled',
  'method_not_allowed',
  'not_found',
  'serve_error',
  'api_route_not_found',
  'api_authentication',
  'api_invalid_request',
  'api_redirect_blocked',
  'api_upstream_rejected',
  'api_invalid_response',
  'api_upstream_failure',
  'listen_error',
  'startup_configuration',
]);
const events = new Set(['portal_request', 'portal_started', 'portal_server_error']);

/** Rebuild known structured events from bounded values; never export URLs, bodies, or headers. */
export function safeLog(record) {
  if (!events.has(record.event)) return undefined;
  const safe = { event: record.event };
  for (const [key, choices] of [
    ['route', routes],
    ['errorCategory', categories],
    ['method', new Set(['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH', 'OTHER'])],
    ['outcome', new Set(['success', 'failure', 'aborted'])],
    ['cloud', new Set(['commercial', 'government'])],
  ]) {
    if (choices.has(record[key])) safe[key] = record[key];
  }
  for (const [key, max] of [
    ['status', 599],
    ['durationMs', 86_400_000],
    ['port', 65_535],
  ]) {
    if (Number.isFinite(record[key]) && record[key] >= 0 && record[key] <= max)
      safe[key] = Math.round(record[key]);
  }
  for (const key of ['browserTelemetry']) {
    if (typeof record[key] === 'boolean') safe[key] = record[key];
  }
  if (typeof record.correlationId === 'string' && uuid.test(record.correlationId))
    safe.correlationId = record.correlationId;
  for (const [key, pattern] of [
    ['traceId', /^[0-9a-f]{32}$/],
    ['spanId', /^[0-9a-f]{16}$/],
  ]) {
    if (typeof record[key] === 'string' && pattern.test(record[key]) && !/^0+$/.test(record[key]))
      safe[key] = record[key];
  }
  return safe;
}

/** Accept only valid W3C version-00 IDs for correlation; trace context does not convey identity. */
function parentContext(value) {
  const match = typeof value === 'string' && traceparent.exec(value);
  if (!match || /^0+$/.test(match[1]) || /^0+$/.test(match[2])) return ROOT_CONTEXT;
  return trace.setSpanContext(ROOT_CONTEXT, {
    traceId: match[1],
    spanId: match[2],
    traceFlags: Number(match[3]),
    isRemote: true,
  });
}

/**
 * Create opt-in server tracing/logging separately from the browser Application Insights SDK.
 * Private providers avoid auto collectors, global registration, resource detectors, and disk retry.
 * Exporters may be injected for deterministic tests; invalid optional configuration disables export.
 */
export function createServerTelemetry(config, exporters = {}) {
  const validated = publicAppInsights(config.appInsights?.connectionString, config.cloud);
  if (!validated) return undefined;
  let tracerProvider;
  let loggerProvider;
  try {
    // Exporter auxiliary telemetry has separate destinations and is not part of our allowlist.
    process.env.APPLICATION_INSIGHTS_NO_STATSBEAT = 'true';
    process.env.APPLICATIONINSIGHTS_STATSBEAT_DISABLED = 'true';
    process.env.APPLICATIONINSIGHTS_SDKSTATS_DISABLED = 'true';
    process.env.APPLICATIONINSIGHTS_OPENTELEMETRY_RESOURCE_METRIC_DISABLED = 'true';
    const options = { connectionString: validated.connectionString, disableOfflineStorage: true };
    const resource = resourceFromAttributes({
      'service.name': 'ai-budget-portal',
      'service.namespace': 'apim-rate-limit-foundry',
    });
    tracerProvider = new BasicTracerProvider({
      resource,
      spanProcessors: [
        new BatchSpanProcessor(exporters.traceExporter ?? new AzureMonitorTraceExporter(options), {
          maxQueueSize: 512,
          maxExportBatchSize: 128,
          exportTimeoutMillis: 3000,
        }),
      ],
    });
    loggerProvider = new LoggerProvider({
      resource,
      forceFlushTimeoutMillis: 3000,
      processors: [
        new BatchLogRecordProcessor(exporters.logExporter ?? new AzureMonitorLogExporter(options), {
          maxQueueSize: 512,
          maxExportBatchSize: 128,
          exportTimeoutMillis: 3000,
        }),
      ],
    });
    const tracer = tracerProvider.getTracer('portal-manual');
    const logger = loggerProvider.getLogger('portal-manual');
    let stopped = false;
    return {
      /** Start a server span from validated incoming context without capturing request contents. */
      request(headers, method) {
        if (stopped) return undefined;
        const span = tracer.startSpan(
          'portal request',
          {
            kind: SpanKind.SERVER,
            attributes: { 'http.method': method },
          },
          parentContext(headers?.traceparent),
        );
        const context = trace.setSpan(ROOT_CONTEXT, span);
        const { traceId, spanId } = span.spanContext();
        return {
          traceId,
          spanId,
          context,
          end(record) {
            const safe = safeLog(record);
            span.updateName(`${method} ${safe.route ?? 'other'}`);
            span.setAttributes({ ...safe, 'http.status_code': safe.status ?? 0 });
            span.setStatus({
              code: safe.outcome === 'success' ? SpanStatusCode.OK : SpanStatusCode.ERROR,
            });
            span.end();
          },
        };
      },
      /** Create a child APIM span and outgoing traceparent without capturing request paths or keys. */
      dependency(request, method, upstreamOrigin) {
        if (stopped) return undefined;
        const attributes = { 'http.method': method };
        try {
          const endpoint = new URL(upstreamOrigin);
          if (
            endpoint.protocol === 'https:' &&
            !endpoint.username &&
            !endpoint.password &&
            !endpoint.search &&
            !endpoint.hash &&
            endpoint.pathname === '/'
          ) {
            attributes['peer.service'] = endpoint.host;
          }
        } catch {
          // Invalid optional topology context must not affect forwarding.
        }
        const span = tracer.startSpan(
          `${method} portal_api`,
          {
            kind: SpanKind.CLIENT,
            attributes,
          },
          request?.context ?? ROOT_CONTEXT,
        );
        const { traceId, spanId, traceFlags } = span.spanContext();
        let ended = false;
        return {
          traceparent: `00-${traceId}-${spanId}-${traceFlags & 1 ? '01' : '00'}`,
          end(status, category) {
            if (ended) return;
            ended = true;
            span.setAttributes({
              'http.status_code':
                Number.isInteger(status) && status >= 0 && status <= 599 ? status : 0,
              errorCategory: categories.has(category) ? category : 'api_upstream_failure',
            });
            span.setStatus({
              code:
                status >= 200 && status < 300 && category === 'none'
                  ? SpanStatusCode.OK
                  : SpanStatusCode.ERROR,
            });
            span.end();
          },
        };
      },
      /** Correlate sanitized structured diagnostics with a request when available. */
      log(record, request) {
        if (stopped) return;
        const safe = safeLog(record);
        if (safe)
          logger.emit({
            body: safe.event,
            attributes: safe,
            context: request?.context ?? ROOT_CONTEXT,
            severityNumber:
              safe.outcome === 'failure' || safe.event === 'portal_server_error' ? 17 : 9,
          });
      },
      /** Attempt both exporters even if one fails; never promote telemetry errors to API failures. */
      async flush() {
        await Promise.allSettled([tracerProvider.forceFlush(), loggerProvider.forceFlush()]);
      },
      /** Stop accepting records and release both providers at most once. */
      async shutdown() {
        if (stopped) return;
        stopped = true;
        await Promise.allSettled([tracerProvider.shutdown(), loggerProvider.shutdown()]);
      },
    };
  } catch {
    void tracerProvider?.shutdown().catch(() => {});
    void loggerProvider?.shutdown().catch(() => {});
    return undefined;
  }
}
