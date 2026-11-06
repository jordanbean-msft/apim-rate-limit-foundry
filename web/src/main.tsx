import { StrictMode, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MsalProvider, useMsal } from '@azure/msal-react';
import { InteractionRequiredAuthError, InteractionStatus } from '@azure/msal-browser';
import { Button, FluentProvider, Spinner, webLightTheme } from '@fluentui/react-components';
import { createApi } from './api';
import { createMsal, tokenRoles } from './auth';
import type { Role, RuntimeConfig } from './contracts';
import { createDemoApi } from './demo';
import { Portal } from './Portal';
import { initializeTelemetry, track } from './telemetry';
import { TelemetryBoundary } from './TelemetryBoundary';
import './styles.css';

function CloudSession({ config }: { config: RuntimeConfig }) {
  const { instance, accounts, inProgress } = useMsal();
  const account = accounts[0];
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState('');
  const [interactionRequired, setInteractionRequired] = useState(false);
  const api = useMemo(
    () =>
      createApi(config.apiBaseUrl, async () => {
        if (!account) throw new Error('Sign in before calling the API.');
        const result = await instance.acquireTokenSilent({
          account,
          scopes: [config.apiScope],
        });
        return result.accessToken;
      }),
    [instance, account, config],
  );

  useEffect(() => {
    if (!account || inProgress !== InteractionStatus.None) return;
    let active = true;
    instance
      .acquireTokenSilent({ account, scopes: [config.apiScope] })
      .then((result) => {
        if (active) {
          track('portal_bootstrap', { action: 'authentication', outcome: 'success' });
          setRoles(tokenRoles(result.accessToken));
          setError('');
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          track('portal_bootstrap', { action: 'authentication', outcome: 'failure' });
          setInteractionRequired(cause instanceof InteractionRequiredAuthError);
          setError(
            'Unable to authorize this API session. Check configuration and consent, then sign in again.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [instance, account, config.apiScope, inProgress]);

  const signIn = () => {
    void instance.loginRedirect({ scopes: [config.apiScope], account }).catch(() => {
      track('portal_bootstrap', { action: 'sign_in', outcome: 'failure' });
      setError('Sign-in could not start. Check your connection and tenant configuration.');
    });
  };

  if (!account || roles === null) {
    return (
      <main className="welcome">
        <div className="welcome-card">
          <div className="eyebrow">AI BUDGET CONTROL</div>
          <h1>
            Intelligent services.
            <br />
            Intentional spending.
          </h1>
          <p>One place to govern AI budgets, understand usage, and follow every decision.</p>
          <div className="cloud-pill">
            {config.cloud === 'government' ? 'Azure Government' : 'Azure Commercial'} · Entra
            protected
          </div>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          {inProgress !== InteractionStatus.None ? (
            <Spinner label="Completing secure sign-in…" />
          ) : (
            <Button appearance="primary" size="large" onClick={signIn}>
              {interactionRequired ? 'Authorize API access' : 'Sign in with Microsoft'}
            </Button>
          )}
          <p className="fine-print">
            Access is governed by your organization. No data is shown before authentication.
          </p>
        </div>
      </main>
    );
  }
  return (
    <Portal
      api={api}
      roles={roles}
      identity={account.name || account.username}
      cloud={config.cloud}
      onSignOut={() => {
        void instance.logoutRedirect({ account }).catch(() => {
          track('portal_bootstrap', { action: 'sign_out', outcome: 'failure' });
          setError('Sign-out could not start. Please retry.');
        });
      }}
    />
  );
}

function Bootstrap() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    fetch('/config.json', { cache: 'no-store', credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Configuration not available');
        const value = (await response.json()) as RuntimeConfig;
        if (
          !['commercial', 'government'].includes(value.cloud) ||
          typeof value.demoMode !== 'boolean'
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
