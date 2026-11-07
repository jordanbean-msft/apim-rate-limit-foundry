const collections = new Set([
  'models',
  'subscriptions',
  'policies',
  'prices',
  'assignments',
  'usage',
  'audit',
  'reconciliation',
]);
const editableCollections = new Set(['policies', 'prices', 'assignments']);
const tokenPattern = /^[A-Za-z0-9._~-]+$/;
const correlationPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const maxRequestBytes = 1024 * 1024;
const maxResponseBytes = 2 * 1024 * 1024;
const dashboardMaxResponseBytes = 4 * 1024 * 1024;
const requestTimeoutMs = 10_000;
const dashboardTimeoutMs = 45_000;

function configuredEndpoint(value) {
  if (typeof value !== 'string' || !value) throw new Error('Proxy upstream is required');
  const endpoint = new URL(value);
  if (
    endpoint.protocol !== 'https:' ||
    endpoint.username ||
    endpoint.password ||
    endpoint.search ||
    endpoint.hash ||
    endpoint.pathname.replace(/\/+$/, '') !== '/portal'
  ) {
    throw new Error('Proxy upstream must be an HTTPS APIM /portal endpoint');
  }
  return endpoint;
}

function configuredKey(value) {
  const key = typeof value === 'string' ? value.trim() : '';
  if (
    !key ||
    /^@Microsoft\.KeyVault\(/i.test(key) ||
    key.length > 4096 ||
    [...key].some((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint <= 0x20 || codePoint === 0x7f;
    })
  ) {
    throw new Error('Portal APIM subscription key is unavailable');
  }
  return key;
}

function apiTarget(req, endpoint) {
  let url;
  try {
    url = new URL(req.url || '/', 'http://portal.local');
  } catch {
    return null;
  }
  if (url.origin !== 'http://portal.local' || !url.pathname.startsWith('/api/')) return null;
  let path;
  try {
    path = decodeURIComponent(url.pathname.slice('/api/'.length));
  } catch {
    return null;
  }
  if (!path || path.includes('\\') || path.split('/').includes('..')) return null;

  let upstreamPath;
  if (path === 'dashboard' && req.method === 'GET') {
    if (
      url.searchParams.size !== 1 ||
      [...url.searchParams.keys()].some((key) => key !== 'period')
    ) {
      return null;
    }
    const period = url.searchParams.get('period');
    if (!['1h', '24h', '7d'].includes(period)) return null;
    upstreamPath = `${path}?period=${period}`;
  } else if (path === 'usage/callers' && req.method === 'GET') {
    if (url.searchParams.size > 1 || [...url.searchParams.keys()].some((key) => key !== 'period')) {
      return null;
    }
    const period = url.searchParams.get('period') || 'day';
    if (!['hour', 'day'].includes(period)) return null;
    upstreamPath = `${path}?period=${period}`;
  } else if (collections.has(path) && req.method === 'GET' && url.search === '') {
    upstreamPath = path;
  } else {
    const match = /^(policies|prices|assignments)\/([A-Za-z0-9._-]{1,256})$/.exec(path);
    if (
      !match ||
      !editableCollections.has(match[1]) ||
      !['PUT', 'DELETE'].includes(req.method || '') ||
      url.search !== ''
    ) {
      return null;
    }
    upstreamPath = `${match[1]}/${encodeURIComponent(match[2])}`;
  }

  return new URL(`${endpoint.pathname.replace(/\/+$/, '')}/${upstreamPath}`, endpoint.origin);
}

async function requestBody(req) {
  if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(req.headers['content-type'] || '')) {
    throw new Error('invalid_content_type');
  }
  if (Number(req.headers['content-length'] || 0) > maxRequestBytes) {
    throw new Error('request_too_large');
  }
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    const value = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += value.length;
    if (size > maxRequestBytes) throw new Error('request_too_large');
    chunks.push(value);
  }
  if (!size) throw new Error('empty_body');
  const body = Buffer.concat(chunks).toString('utf8');
  try {
    JSON.parse(body);
  } catch {
    throw new Error('invalid_json');
  }
  return body;
}

async function responseBody(response, limit) {
  const length = Number(response.headers.get('content-length') || 0);
  if (length > limit) throw new Error('upstream_response_too_large');
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        throw new Error('upstream_response_too_large');
      }
      chunks.push(Buffer.from(value));
    }
  } finally {
    reader.releaseLock();
  }
  return Buffer.concat(chunks);
}

function send(res, status, body = '', contentType = 'application/json; charset=utf-8') {
  res.writeHead(status, {
    'Content-Type': contentType,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(body);
}

export function createApiProxy({ upstreamUrl, subscriptionKey, fetchImpl = fetch }) {
  const endpoint = configuredEndpoint(upstreamUrl);
  const key = configuredKey(subscriptionKey);

  return async function proxy(req, res, outcome = {}) {
    const target = apiTarget(req, endpoint);
    if (!target) {
      outcome.errorCategory = 'api_route_not_found';
      send(res, 404, JSON.stringify({ error: 'API route not found.' }));
      return;
    }
    const accessToken = req.headers['x-portal-access-token'];
    if (
      typeof accessToken !== 'string' ||
      accessToken.length > 16_384 ||
      !accessToken.split('.').every((part) => part.length > 0 && tokenPattern.test(part)) ||
      accessToken.split('.').length !== 3
    ) {
      outcome.errorCategory = 'api_authentication';
      send(res, 401, JSON.stringify({ error: 'A valid portal access token is required.' }));
      return;
    }

    let body;
    if (req.method === 'PUT') {
      try {
        req.setTimeout(requestTimeoutMs, () => req.destroy());
        body = await requestBody(req);
      } catch (error) {
        const category = error instanceof Error ? error.message : '';
        outcome.errorCategory = 'api_invalid_request';
        const status =
          category === 'request_too_large'
            ? 413
            : category === 'invalid_content_type' || category === 'invalid_json'
              ? 400
              : 400;
        send(res, status, JSON.stringify({ error: 'Invalid API request body.' }));
        return;
      }
    } else if (
      (req.headers['content-length'] && Number(req.headers['content-length']) > 0) ||
      req.headers['transfer-encoding']
    ) {
      outcome.errorCategory = 'api_invalid_request';
      send(res, 400, JSON.stringify({ error: 'This API request does not accept a body.' }));
      return;
    }

    const headers = {
      Authorization: `Bearer ${accessToken}`,
      'Ocp-Apim-Subscription-Key': key,
    };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const correlationId = req.headers['x-correlation-id'];
    if (typeof correlationId === 'string' && correlationPattern.test(correlationId)) {
      headers['X-Correlation-ID'] = correlationId;
    }

    try {
      const isDashboard = target.pathname.endsWith('/dashboard');
      const response = await fetchImpl(target, {
        method: req.method,
        headers,
        body,
        redirect: 'manual',
        signal: AbortSignal.timeout(isDashboard ? dashboardTimeoutMs : requestTimeoutMs),
      });
      if (response.status >= 300 && response.status < 400) {
        outcome.errorCategory = 'api_redirect_blocked';
        await response.body?.cancel();
        send(res, 502, JSON.stringify({ error: 'The API returned an unsupported redirect.' }));
        return;
      }
      if (!response.ok) {
        outcome.errorCategory = 'api_upstream_rejected';
        await response.body?.cancel();
        send(res, response.status, JSON.stringify({ error: 'The API request was denied.' }));
        return;
      }
      if (response.status === 204) {
        send(res, 204, '');
        return;
      }
      const contentType = response.headers.get('content-type') || '';
      if (!/^application\/(?:[a-z0-9.+-]+\+)?json(?:\s*;|$)/i.test(contentType)) {
        outcome.errorCategory = 'api_invalid_response';
        await response.body?.cancel();
        send(res, 502, JSON.stringify({ error: 'The API returned an invalid response.' }));
        return;
      }
      const result = await responseBody(
        response,
        isDashboard ? dashboardMaxResponseBytes : maxResponseBytes,
      );
      send(res, response.status, result);
    } catch {
      outcome.errorCategory = 'api_upstream_failure';
      send(res, 502, JSON.stringify({ error: 'The API could not complete this request.' }));
    }
  };
}
