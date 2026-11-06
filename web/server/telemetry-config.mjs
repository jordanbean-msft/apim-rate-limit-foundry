const guid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Invalid optional telemetry disables export, never authentication or the portal. */
export function publicAppInsights(connectionString, cloud) {
  if (typeof connectionString !== 'string' || connectionString.length > 4096) return undefined;
  const fields = new Map();
  for (const part of connectionString.split(';').filter(Boolean)) {
    const index = part.indexOf('=');
    if (index < 1) return undefined;
    const key = part.slice(0, index).trim().toLowerCase();
    if (fields.has(key)) return undefined;
    fields.set(key, part.slice(index + 1).trim());
  }
  const key = fields.get('instrumentationkey');
  const endpoint = fields.get('ingestionendpoint');
  if (!key || !guid.test(key) || !endpoint) return undefined;
  try {
    const url = new URL(endpoint);
    const suffixes =
      cloud === 'commercial'
        ? ['applicationinsights.azure.com']
        : cloud === 'government'
          ? ['applicationinsights.us', 'applicationinsights.azure.us']
          : [];
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      url.port ||
      url.search ||
      url.hash ||
      url.pathname !== '/' ||
      !suffixes.some((suffix) => url.hostname === suffix || url.hostname.endsWith(`.${suffix}`))
    )
      return undefined;
    return {
      connectionString: `InstrumentationKey=${key};IngestionEndpoint=${url.origin}/`,
      ingestionOrigin: url.origin,
    };
  } catch {
    return undefined;
  }
}
