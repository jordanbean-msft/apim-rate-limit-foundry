import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MsalProvider } from '@azure/msal-react';
import { Button, FluentProvider, Spinner, webLightTheme } from '@fluentui/react-components';
import { createMsal } from './auth';
import { CloudSession } from './CloudSession';
import type { RuntimeConfig } from './contracts';
import { createDemoApi } from './demo';
import { Portal } from './Portal';
import { initializeTelemetry, track } from './telemetry';
import { TelemetryBoundary } from './TelemetryBoundary';
import './styles.css';

const portalTheme = {
  ...webLightTheme,
  fontFamilyBase: 'system-ui, sans-serif',
  fontFamilyNumeric: 'system-ui, sans-serif',
  fontFamilyMonospace: 'system-ui, sans-serif',
  borderRadiusSmall: '0',
  borderRadiusMedium: '0',
  borderRadiusLarge: '0',
  borderRadiusXLarge: '0',
  borderRadiusCircular: '0',
  shadow2: 'none',
  shadow4: 'none',
  shadow8: 'none',
  shadow16: 'none',
  shadow28: 'none',
  shadow64: 'none',
};

function Bootstrap() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [msalReady, setMsalReady] = useState(false);
  useEffect(() => {
    let active = true;
    fetch('/config.json', { cache: 'no-store', credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Configuration not available');
        const value = (await response.json()) as RuntimeConfig;
        if (
          !['commercial', 'government'].includes(value.cloud) ||
          typeof value.demoMode !== 'boolean' ||
          typeof value.apiProxyEnabled !== 'boolean'
        ) {
          throw new Error('Invalid public configuration');
        }
        if (active) {
          initializeTelemetry(value);
          track('portal_bootstrap', { action: 'configuration', outcome: 'success' });
          setConfig(value);
          setError('');
        }
      })
      .catch(() => {
        track('portal_bootstrap', { action: 'configuration', outcome: 'failure' });
        if (active)
          setError(
            'The portal is not configured. Set the required web runtime settings and restart the server. No demo fallback was enabled.',
          );
      });
    return () => {
      active = false;
    };
  }, [attempt]);
  const msal = useMemo(() => (config && !config.demoMode ? createMsal(config) : null), [config]);
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
  const demo = useMemo(() => createDemoApi(), []);
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
  if (config.demoMode)
    return (
      <Portal
        api={demo}
        roles={['RateLimit.Admin', 'RateLimit.Reader']}
        identity="Local demo administrator"
        cloud={config.cloud}
        demo
      />
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
    <FluentProvider theme={portalTheme}>
      <TelemetryBoundary>
        <Bootstrap />
      </TelemetryBoundary>
    </FluentProvider>
  </StrictMode>,
);
