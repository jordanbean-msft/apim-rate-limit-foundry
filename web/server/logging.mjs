import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';

export function writeLog(record) {
  try {
    console.info(JSON.stringify({ ...record, timestamp: new Date().toISOString() }));
  } catch {
    // Hosting diagnostics must never change an HTTP outcome.
  }
}

export function observeRequest(req, res, logger = writeLog) {
  const correlationId = randomUUID();
  const start = performance.now();
  const method = ['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'].includes(req.method)
    ? req.method
    : 'OTHER';
  const outcome = { route: 'other', errorCategory: 'none' };
  let completed = false;
  res.setHeader('X-Correlation-ID', correlationId);
  const emit = (aborted) => {
    if (completed) return;
    completed = true;
    try {
      logger({
        event: 'portal_request',
        correlationId,
        method,
        route: outcome.route,
        status: aborted ? 0 : res.statusCode,
        durationMs: Math.round(performance.now() - start),
        outcome: aborted ? 'aborted' : res.statusCode < 400 ? 'success' : 'failure',
        errorCategory: aborted ? 'connection_closed' : outcome.errorCategory,
      });
    } catch {
      // A failing sink must not break static serving.
    }
  };
  res.once('finish', () => emit(false));
  res.once('close', () => emit(!res.writableFinished));
  return outcome;
}
