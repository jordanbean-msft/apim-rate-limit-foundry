// @vitest-environment node
import { once } from 'node:events';
import { EventEmitter } from 'node:events';
import { request as httpRequest } from 'node:http';
import type { AddressInfo } from 'node:net';
import { SpanKind, SpanStatusCode } from '@opentelemetry/api';
import type { ReadableSpan } from '@opentelemetry/sdk-trace-base';
import type { ReadableLogRecord } from '@opentelemetry/sdk-logs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createServerTelemetry, safeLog } from '../server/telemetry.mjs';
import { createPortalServer } from '../server/index.mjs';
import { observeRequest } from '../server/logging.mjs';

const config = {
  cloud: 'government',
  apiBaseUrl: '/api',
  apiProxyEnabled: true,
  appInsights: {
    connectionString:
      'InstrumentationKey=11111111-1111-1111-1111-111111111111;IngestionEndpoint=https://dc.applicationinsights.us/',
  },
};
const browserTrace = '1234567890abcdef1234567890abcdef';
const browserSpan = '1234567890abcdef';
const correlationId = '12345678-1234-4123-8123-123456789012';
const instances: NonNullable<ReturnType<typeof createServerTelemetry>>[] = [];
const servers: ReturnType<typeof createPortalServer>[] = [];

function telemetryFixture() {
  const spans: ReadableSpan[] = [];
  const logs: ReadableLogRecord[] = [];
  const traceExporter = {
    export: vi.fn((batch: ReadableSpan[], done: (result: { code: number }) => void) => {
      spans.push(...batch);
      done({ code: 0 });
    }),
    shutdown: vi.fn(async () => {}),
  };
  const logExporter = {
    export: vi.fn((batch: ReadableLogRecord[], done: (result: { code: number }) => void) => {
      logs.push(...batch);
      done({ code: 0 });
    }),
    shutdown: vi.fn(async () => {}),
  };
  const telemetry = createServerTelemetry(config, { traceExporter, logExporter })!;
  expect(telemetry).toBeDefined();
  instances.push(telemetry);
  return { telemetry, spans, logs, traceExporter, logExporter };
}

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((done) => {
          server.close(() => done());
          server.closeAllConnections();
        }),
    ),
  );
  await Promise.all(instances.splice(0).map((instance) => instance.shutdown()));
});

describe('manual private server export', () => {
  it('initializes the real Microsoft exporters with all auxiliary telemetry disabled', async () => {
    const telemetry = createServerTelemetry(config);
    expect(telemetry).toBeDefined();
    expect(process.env.APPLICATION_INSIGHTS_NO_STATSBEAT).toBe('true');
    expect(process.env.APPLICATIONINSIGHTS_STATSBEAT_DISABLED).toBe('true');
    expect(process.env.APPLICATIONINSIGHTS_SDKSTATS_DISABLED).toBe('true');
    expect(process.env.APPLICATIONINSIGHTS_OPENTELEMETRY_RESOURCE_METRIC_DISABLED).toBe('true');
    await telemetry?.shutdown();
  });

  it('cancels the upstream on browser disconnect and exports both terminal spans once', async () => {
    const { telemetry, spans, logs } = telemetryFixture();
    let started!: () => void;
    let aborted!: () => void;
    const upstreamStarted = new Promise<void>((done) => {
      started = done;
    });
    const upstreamAborted = new Promise<void>((done) => {
      aborted = done;
    });
    const server = createPortalServer(config, '.', vi.fn(), {
      upstreamUrl: 'https://private-gateway.example/portal',
      subscriptionKey: 'private-key',
      telemetry,
      fetchImpl: (_target: URL, options: { signal: AbortSignal }) =>
        new Promise<Response>((_done, reject) => {
          options.signal.addEventListener(
            'abort',
            () => {
              aborted();
              reject(new Error('private upstream cancellation'));
            },
            { once: true },
          );
          started();
        }),
    });
    servers.push(server);
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const client = httpRequest({
      host: '127.0.0.1',
      port: (server.address() as AddressInfo).port,
      path: '/api/models',
      headers: { 'X-Portal-Access-Token': 'private.access.token' },
    });
    client.on('error', () => {});
    client.end();
    await upstreamStarted;
    client.destroy();
    await upstreamAborted;
    await new Promise<void>((done) => setImmediate(done));
    await telemetry.flush();
    expect(spans).toHaveLength(2);
    expect(spans.every((span) => span.status.code === SpanStatusCode.ERROR)).toBe(true);
    expect(logs).toHaveLength(1);
    expect(logs[0].attributes.outcome).toBe('aborted');
    expect(logs[0].attributes.errorCategory).toBe('connection_closed');
  });

  it.each(['success', 'rejected', 'redirect', 'network', 'invalid_response'] as const)(
    'exports one correlated proxy request/dependency/log for %s without request contents',
    async (result) => {
      const { telemetry, spans, logs } = telemetryFixture();
      const fetchImpl = vi.fn(async () => {
        if (result === 'network') throw new Error('private upstream token/error');
        return new Response('{"private":"response"}', {
          status: result === 'rejected' ? 403 : result === 'redirect' ? 302 : 200,
          headers: {
            'Content-Type': result === 'invalid_response' ? 'text/html' : 'application/json',
          },
        });
      });
      const logger = vi.fn();
      const server = createPortalServer(config, '.', logger, {
        upstreamUrl: 'https://private-gateway.example/portal',
        subscriptionKey: 'private-subscription-key',
        fetchImpl,
        telemetry,
      });
      servers.push(server);
      server.listen(0, '127.0.0.1');
      await once(server, 'listening');
      const port = (server.address() as AddressInfo).port;
      const response = await fetch(`http://127.0.0.1:${port}/api/budgets/private-record`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-Portal-Access-Token': 'private.access.token',
          'X-Correlation-ID': correlationId,
          traceparent: `00-${browserTrace}-${browserSpan}-01`,
          tracestate: 'private=identity',
          baggage: 'private=identity',
          'User-Agent': 'private user agent',
        },
        body: JSON.stringify({ id: 'private-record', prompt: 'private prompt' }),
      });
      await response.text();
      expect(response.status).toBe(result === 'success' ? 200 : result === 'rejected' ? 403 : 502);
      expect(response.headers.get('x-correlation-id')).toBe(correlationId);
      await telemetry.flush();
      expect(spans).toHaveLength(2);
      const request = spans.find((span) => span.kind === SpanKind.SERVER)!;
      const dependency = spans.find((span) => span.kind === SpanKind.CLIENT)!;
      expect(request.parentSpanContext?.spanId).toBe(browserSpan);
      expect(request.spanContext().traceId).toBe(browserTrace);
      expect(dependency.parentSpanContext?.spanId).toBe(request.spanContext().spanId);
      expect(dependency.spanContext().traceId).toBe(browserTrace);
      const headers = fetchImpl.mock.calls[0] as unknown as [
        URL,
        { headers: Record<string, string> },
      ];
      expect(headers[1].headers.traceparent).toBe(
        `00-${browserTrace}-${dependency.spanContext().spanId}-01`,
      );
      expect(headers[1].headers['X-Correlation-ID']).toBe(correlationId);
      expect(headers[1].headers).not.toHaveProperty('tracestate');
      expect(headers[1].headers).not.toHaveProperty('baggage');
      expect(dependency.status.code).toBe(
        result === 'success' ? SpanStatusCode.OK : SpanStatusCode.ERROR,
      );
      expect(logs).toHaveLength(1);
      expect(logs[0].body).toBe('portal_request');
      expect(logs[0].spanContext?.spanId).toBe(request.spanContext().spanId);
      expect(logs[0].attributes.correlationId).toBe(correlationId);
      expect(logger).toHaveBeenCalledOnce();
      const exported = {
        spans: spans.map((span) => ({
          name: span.name,
          attributes: span.attributes,
          resource: span.resource.attributes,
          events: span.events,
        })),
        logs: logs.map((log) => ({
          body: log.body,
          attributes: log.attributes,
          resource: log.resource.attributes,
        })),
        console: logger.mock.calls,
      };
      expect(JSON.stringify(exported)).not.toContain('private');
      expect(request.resource.attributes['service.name']).toBe('ai-budget-portal');
      expect(Object.keys(request.resource.attributes).sort()).toEqual([
        'service.name',
        'service.namespace',
      ]);
    },
  );

  it.each([
    '00-00000000000000000000000000000000-1234567890abcdef-01',
    '00-1234567890abcdef1234567890abcdef-0000000000000000-01',
    'private query?token=secret',
    ['00-1234567890abcdef1234567890abcdef-1234567890abcdef-01'],
  ])('rejects invalid or ambiguous incoming context: %j', async (traceparent) => {
    const { telemetry, spans } = telemetryFixture();
    const request = telemetry.request({ traceparent }, 'GET')!;
    request.end({ event: 'portal_request', route: 'api_proxy', status: 200, outcome: 'success' });
    await telemetry.flush();
    expect(spans[0].parentSpanContext).toBeUndefined();
    expect(spans[0].spanContext().traceId).not.toBe(browserTrace);
  });

  it('exports abort only once, sanitizes logs, and shuts down idempotently', async () => {
    const { telemetry, spans, logs, traceExporter, logExporter } = telemetryFixture();
    const res = Object.assign(new EventEmitter(), {
      setHeader: vi.fn(),
      statusCode: 200,
      writableFinished: false,
    });
    observeRequest({ method: 'GET', headers: {} }, res, vi.fn(), telemetry);
    res.emit('close');
    res.emit('finish');
    telemetry.log(
      { event: 'portal_started', cloud: 'government', token: 'private token' },
      undefined,
    );
    telemetry.log({ event: 'private unknown event' }, undefined);
    await telemetry.flush();
    expect(spans).toHaveLength(1);
    expect(spans[0].status.code).toBe(SpanStatusCode.ERROR);
    expect(logs).toHaveLength(2);
    expect(JSON.stringify(logs.map((log) => log.attributes))).not.toContain('private');
    await telemetry.shutdown();
    await telemetry.shutdown();
    expect(traceExporter.shutdown).toHaveBeenCalledOnce();
    expect(logExporter.shutdown).toHaveBeenCalledOnce();
    expect(telemetry.request({}, 'GET')).toBeUndefined();
    expect(telemetry.dependency(undefined, 'GET')).toBeUndefined();
  });

  it('disables export for an invalid endpoint and rejects arbitrary log context', () => {
    expect(createServerTelemetry({ ...config, appInsights: undefined })).toBeUndefined();
    expect(createServerTelemetry({ ...config, cloud: 'commercial' })).toBeUndefined();
    expect(
      safeLog({
        event: 'portal_server_error',
        errorCategory: 'private exception',
        correlationId: 'private-user',
        status: Infinity,
        durationMs: -1,
        url: 'private-url',
        traceId: '0'.repeat(32),
      }),
    ).toEqual({ event: 'portal_server_error' });
  });

  it('does not let failing telemetry change the HTTP result or console logging', () => {
    const fail = () => {
      throw new Error('private exporter failure');
    };
    const res = Object.assign(new EventEmitter(), {
      setHeader: vi.fn(),
      statusCode: 200,
      writableFinished: true,
    });
    const logger = vi.fn();
    expect(() => {
      observeRequest({ method: 'GET', headers: {} }, res, logger, { request: fail, log: fail });
      res.emit('finish');
    }).not.toThrow();
    expect(logger).toHaveBeenCalledOnce();
  });
});
