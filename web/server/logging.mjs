import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { safeLog } from './telemetry.mjs';

/** Write allowlisted structured records only; discard arbitrary fields before console output. */
export function writeLog(record) {
  try {
    const safe = safeLog(record);
    if (safe) console.info(JSON.stringify({ ...safe, timestamp: new Date().toISOString() }));
  } catch {
    // Hosting diagnostics must never change an HTTP outcome.
  }
}

/**
 * Observe one HTTP lifecycle and return mutable route/error metadata for the handler to populate.
 * Correlation UUIDs and trace IDs link diagnostics without recording URLs, cookies, or identities.
 */
export function observeRequest(req, res, logger = writeLog, telemetry) {
  const suppliedId = req.headers?.['x-correlation-id'];
  const correlationId =
    typeof suppliedId === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(suppliedId)
      ? suppliedId
      : randomUUID();
  const start = performance.now();
  const method = ['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'].includes(req.method)
    ? req.method
    : 'OTHER';
  const outcome = { route: 'other', errorCategory: 'none' };
  let request;
  try {
    request = telemetry?.request(req.headers, method);
  } catch {
    // Telemetry must not affect request handling.
  }
  // Keep tracing context and correlation metadata non-enumerable in the mutable handler outcome.
  Object.defineProperties(outcome, {
    request: { value: request },
    correlationId: { value: correlationId },
  });
  let completed = false;
  res.setHeader('X-Correlation-ID', correlationId);
  // finish and close can both fire; emit once and use status 0 for an incomplete connection.
  const emit = (aborted) => {
    if (completed) return;
    completed = true;
    try {
      const record = {
        event: 'portal_request',
        correlationId,
        method,
        route: outcome.route,
        status: aborted ? 0 : res.statusCode,
        durationMs: Math.round(performance.now() - start),
        outcome: aborted ? 'aborted' : res.statusCode < 400 ? 'success' : 'failure',
        errorCategory: aborted ? 'connection_closed' : outcome.errorCategory,
        ...(request ? { traceId: request.traceId, spanId: request.spanId } : {}),
      };
      try {
        request?.end(record);
        telemetry?.log(record, request);
      } catch {
        // A failing exporter must not suppress console diagnostics.
      }
      logger(record);
    } catch {
      // A failing sink must not break static serving.
    }
  };
  res.once('finish', () => emit(false));
  res.once('close', () => emit(!res.writableFinished));
  return outcome;
}
