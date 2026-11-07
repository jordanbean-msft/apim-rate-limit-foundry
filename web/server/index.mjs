import { createServer } from 'node:http';
import { readFile, realpath, stat } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { authorityFor, buildConfig } from './runtime-config.mjs';
import { createApiProxy } from './api-proxy.mjs';
import { observeRequest, writeLog } from './logging.mjs';
import { publicAppInsights } from './telemetry-config.mjs';

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

export function createPortalServer(
  config,
  root = resolve('dist'),
  logger = writeLog,
  proxyOptions = {},
) {
  root = resolve(root);
  const apiOrigin = config.apiBaseUrl?.startsWith('https://')
    ? new URL(config.apiBaseUrl).origin
    : '';
  const authority = authorityFor(config.cloud);
  const graphOrigin =
    config.cloud === 'government' ? 'https://graph.microsoft.us' : 'https://graph.microsoft.com';
  const apiProxy = config.apiProxyEnabled ? createApiProxy(proxyOptions) : null;
  const ingestionOrigin =
    publicAppInsights(config.appInsights?.connectionString, config.cloud)?.ingestionOrigin || '';
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${authority} ${graphOrigin} ${apiOrigin} ${ingestionOrigin}`,
    `frame-src 'self' ${authority}`,
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
  ].join('; ');
  return createServer(async (req, res) => {
    const outcome = observeRequest(req, res, logger);
    res.setHeader('Content-Security-Policy', csp);
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(), geolocation=()');
    let pathname;
    try {
      pathname = decodeURIComponent((req.url || '/').split('?')[0]);
    } catch {
      outcome.errorCategory = 'invalid_path';
      res.writeHead(400).end('Invalid path');
      return;
    }
    if (pathname.startsWith('/api/')) {
      outcome.route = 'api_proxy';
      if (!apiProxy) {
        outcome.errorCategory = 'proxy_disabled';
        res.writeHead(404).end('Not found');
        return;
      }
      await apiProxy(req, res, outcome);
      return;
    }
    if (!['GET', 'HEAD'].includes(req.method || '')) {
      outcome.errorCategory = 'method_not_allowed';
      res.writeHead(405, { Allow: 'GET, HEAD' }).end();
      return;
    }
    try {
      if (pathname === '/config.json') {
        outcome.route = 'runtime_config';
        res.writeHead(200, {
          'Content-Type': 'application/json',
          'Cache-Control': 'no-store',
        });
        res.end(req.method === 'HEAD' ? undefined : JSON.stringify(config));
        return;
      }
      if (
        pathname.includes('\0') ||
        pathname.includes('\\') ||
        pathname.split('/').includes('..')
      ) {
        outcome.errorCategory = 'invalid_path';
        res.writeHead(400).end('Invalid path');
        return;
      }
      let filename = resolve(root, `.${pathname}`);
      if (!filename.startsWith(`${root}${sep}`) && filename !== root) {
        outcome.errorCategory = 'invalid_path';
        res.writeHead(400).end('Invalid path');
        return;
      }
      outcome.route = pathname === '/' || pathname === '/index.html' ? 'page' : 'asset';
      if (pathname === '/') filename = resolve(root, 'index.html');
      try {
        if (!(await stat(filename)).isFile()) throw new Error('Not a file');
      } catch {
        if (extname(pathname) || !req.headers.accept?.includes('text/html')) {
          outcome.errorCategory = 'not_found';
          res.writeHead(404).end('Not found');
          return;
        }
        filename = resolve(root, 'index.html');
        outcome.route = 'page';
      }
      const [realRoot, realFile] = await Promise.all([realpath(root), realpath(filename)]);
      if (!realFile.startsWith(`${realRoot}${sep}`)) {
        outcome.errorCategory = 'invalid_path';
        res.writeHead(400).end('Invalid path');
        return;
      }
      const content = await readFile(realFile);
      res.writeHead(200, {
        'Content-Type': mime[extname(filename)] || 'application/octet-stream',
        'Cache-Control': extname(filename) === '.html' ? 'no-cache' : 'public, max-age=3600',
      });
      res.end(req.method === 'HEAD' ? undefined : content);
    } catch (error) {
      outcome.errorCategory = error instanceof URIError ? 'invalid_path' : 'serve_error';
      res.writeHead(error instanceof URIError ? 400 : 500).end('Unable to serve this request');
    }
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  try {
    const config = buildConfig();
    const port = Number(process.env.PORT || 8080);
    const server = createPortalServer(config, resolve('dist'), writeLog, {
      upstreamUrl: process.env.API_BASE_URL,
      subscriptionKey: process.env.PORTAL_APIM_SUBSCRIPTION_KEY,
    });
    server.on('error', () => {
      writeLog({ event: 'portal_server_error', errorCategory: 'listen_error' });
      process.exitCode = 1;
    });
    server.listen(port, '0.0.0.0', () => {
      writeLog({
        event: 'portal_started',
        port,
        cloud: config.cloud,
        demoMode: config.demoMode,
        browserTelemetry: Boolean(config.appInsights),
      });
    });
  } catch {
    writeLog({ event: 'portal_server_error', errorCategory: 'startup_configuration' });
    process.exitCode = 1;
  }
}
