import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MsalProvider } from '@azure/msal-react';
import { Button, FluentProvider, Spinner, webLightTheme } from '@fluentui/react-components';
import { createMsal } from './auth';
import { CloudSession } from './CloudSession';
import type { RuntimeConfig } from './contracts';
import { initializeTelemetry, track } from './telemetry';
import { TelemetryBoundary } from './TelemetryBoundary';
import './styles.css';

/** Load public runtime settings before enabling Entra sign-in. */
function Bootstrap() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [msalReady, setMsalReady] = useState(false);
  useEffect(() => {
    // Retries/unmounts invalidate prior completions without cancelling the configuration fetch.
    let active = true;
    setConfig(null);
    setError('');
    fetch('/config.json', { cache: 'no-store', credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Configuration not available');
        const value = (await response.json()) as RuntimeConfig;
        if (
          !['commercial', 'government'].includes(value.cloud) ||
          typeof value.apiProxyEnabled !== 'boolean'
        ) {
          throw new Error('Invalid public configuration');
        }
        if (!active) return;
        initializeTelemetry(value);
        track('portal_bootstrap', { action: 'configuration', outcome: 'success' });
        setConfig(value);
        setError('');
      })
      .catch(() => {
        track('portal_bootstrap', { action: 'configuration', outcome: 'failure' });
        if (active)
          setError(
            'The portal is not configured. Set the required web runtime settings and restart the server.',
          );
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  const msal = useMemo(() => (config ? createMsal(config) : null), [config]);
  useEffect(() => {
    if (!msal) {
      setMsalReady(false);
      return;
    }
    let active = true;
    setMsalReady(false);
    setError('');
    void msal
      .initialize()
      .then(() => {
        if (active) setMsalReady(true);
      })
      .catch(() => {
        if (!active) return;
        track('portal_bootstrap', { action: 'msal_initialize', outcome: 'failure' });
        setError(
          'Secure sign-in could not initialize. Reload the page and verify tenant configuration.',
        );
      });
    return () => {
      active = false;
    };
  }, [msal]);
  if (error)
    return (
      <main className="welcome">
        <div className="welcome-card">
          <h1>Configuration required</h1>
          <p role="alert">{error}</p>
          <Button onClick={() => setAttempt((value) => value + 1)}>Retry configuration</Button>
        </div>
      </main>
    );
  if (!config)
    return (
      <main className="welcome">
        <Spinner label="Loading secure configuration…" />
      </main>
    );
  if (!msalReady)
    return (
      <main className="welcome">
        <Spinner label="Initializing secure sign-in…" />
      </main>
    );
  return (
    <MsalProvider instance={msal!}>
      <CloudSession config={config} />
    </MsalProvider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FluentProvider theme={webLightTheme}>
      <TelemetryBoundary>
        <Bootstrap />
      </TelemetryBoundary>
    </FluentProvider>
  </StrictMode>,
);
