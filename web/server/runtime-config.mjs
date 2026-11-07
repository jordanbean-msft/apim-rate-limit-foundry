import { publicAppInsights } from './telemetry-config.mjs';

const authorities = {
  commercial: 'https://login.microsoftonline.com',
  government: 'https://login.microsoftonline.us',
};
const guid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Only explicitly allowlisted, public settings ever reach the browser. */
export function buildConfig(env = process.env) {
  const demoMode = env.WEB_DEMO_MODE === 'true';
  const cloud = env.AZURE_CLOUD || (demoMode ? 'commercial' : '');
  if (!Object.hasOwn(authorities, cloud)) throw new Error('Unsupported AZURE_CLOUD');
  if (env.WEB_DEMO_MODE && !['true', 'false'].includes(env.WEB_DEMO_MODE)) {
    throw new Error('WEB_DEMO_MODE must be true or false');
  }
  if (env.WEB_PLATFORM_AUTH_ENABLED && !['true', 'false'].includes(env.WEB_PLATFORM_AUTH_ENABLED)) {
    throw new Error('WEB_PLATFORM_AUTH_ENABLED must be true or false');
  }
  if (env.WEB_API_PROXY_ENABLED && !['true', 'false'].includes(env.WEB_API_PROXY_ENABLED)) {
    throw new Error('WEB_API_PROXY_ENABLED must be true or false');
  }
  const apiProxyEnabled = env.WEB_API_PROXY_ENABLED === 'true';
  const tenantId = env.AZURE_TENANT_ID || '';
  const clientId = env.WEB_CLIENT_ID || '';
  const apiAudience = env.API_AUDIENCE || '';
  const apiScope = env.API_SCOPE || '';
  const apiBaseUrl = (env.API_BASE_URL || '').replace(/\/+$/, '');
  if (!demoMode) {
    if (!guid.test(tenantId) || !guid.test(clientId)) {
      throw new Error('AZURE_TENANT_ID and WEB_CLIENT_ID must be tenant-specific GUIDs');
    }
    if (!/^(api:\/\/|https:\/\/)[^\s?#]+$/.test(apiAudience)) {
      throw new Error('API_AUDIENCE must be an explicit application ID URI');
    }
    if (!apiScope.startsWith(`${apiAudience}/`) || /\s/.test(apiScope)) {
      throw new Error('API_SCOPE must be one full scope under API_AUDIENCE');
    }
    const url = new URL(apiBaseUrl);
    if (url.username || url.password || url.search || url.hash)
      throw new Error('Invalid API_BASE_URL');
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) {
      throw new Error('API_BASE_URL must use HTTPS (except loopback development)');
    }
    if (
      apiProxyEnabled &&
      (url.protocol !== 'https:' || url.pathname.replace(/\/+$/, '') !== '/portal')
    ) {
      throw new Error('Proxied API_BASE_URL must be an HTTPS APIM /portal endpoint');
    }
  }
  return {
    cloud,
    tenantId,
    clientId,
    apiAudience,
    apiScope,
    apiBaseUrl: apiProxyEnabled ? '/api' : apiBaseUrl,
    apiProxyEnabled,
    demoMode,
    platformAuthEnabled: env.WEB_PLATFORM_AUTH_ENABLED === 'true',
    appInsights: publicAppInsights(env.APPLICATIONINSIGHTS_CONNECTION_STRING, cloud),
  };
}

export function authorityFor(cloud) {
  if (!Object.hasOwn(authorities, cloud)) throw new Error('Unsupported Azure cloud');
  return authorities[cloud];
}
