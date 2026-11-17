import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMsal } from '@azure/msal-react';
import { InteractionRequiredAuthError, InteractionStatus } from '@azure/msal-browser';
import { Badge, Button, MessageBar, MessageBarBody, Spinner } from '@fluentui/react-components';
import { createApi } from './api';
import { tokenRoles } from './auth';
import type { Role, RuntimeConfig } from './contracts';
import { ProfileGreeting } from './components/ProfileGreeting';
import { Portal } from './Portal';
import { observeIdentity, track } from './telemetry';

/** Coordinate MSAL identity, API-role hints, and optional Graph profile access after bootstrap. */
export function CloudSession({ config }: { config: RuntimeConfig }) {
  const { instance, accounts, inProgress } = useMsal();
  const account = useMemo(() => instance.getActiveAccount() ?? accounts[0], [instance, accounts]);
  const restoreOnMount = useRef(true);
  const [restoring, setRestoring] = useState(false);
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState('');
  const [interactionRequired, setInteractionRequired] = useState(false);
  const api = useMemo(
    () =>
      createApi(
        config.apiBaseUrl,
        async () => {
          if (!account) throw new Error('Sign in before calling the API.');
          const result = await observeIdentity('token_api', () =>
            instance.acquireTokenSilent({
              account,
              scopes: [config.apiScope],
            }),
          );
          return result.accessToken;
        },
        track,
        config.apiProxyEnabled,
      ),
    [instance, account, config],
  );
  // Graph has its own audience/scope; an API access token must never be reused for profile calls.
  const graphScope =
    config.cloud === 'government'
      ? 'https://graph.microsoft.us/User.Read'
      : 'https://graph.microsoft.com/User.Read';
  const getGraphToken = useCallback(async () => {
    if (!account) throw new Error('Sign in before accessing the profile.');
    const result = await observeIdentity('token_graph', () =>
      instance.acquireTokenSilent({ account, scopes: [graphScope] }),
    );
    return result.accessToken;
  }, [account, graphScope, instance]);

  const signIn = useCallback(() => {
    return instance.loginRedirect({ scopes: [config.apiScope], account }).catch(() => {
      track('portal_bootstrap', { action: 'sign_in', outcome: 'failure' });
      setError('Sign-in could not start. Check your connection and tenant configuration.');
    });
  }, [instance, config.apiScope, account]);

  useEffect(() => {
    if (inProgress !== InteractionStatus.None || !restoreOnMount.current) return;
    restoreOnMount.current = false;
    if (account || !config.platformAuthEnabled) return;
    const key = `portal.sso.${config.clientId}`;
    try {
      // Survives the redirect, but contains no identity or token. Failed SSO must not loop.
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, 'attempted');
    } catch {
      return;
    }
    setRestoring(true);
    void signIn().finally(() => setRestoring(false));
  }, [account, config.clientId, config.platformAuthEnabled, inProgress, signIn]);

  useEffect(() => {
    if (!account || inProgress !== InteractionStatus.None) return;
    // Silent acquisition is not cancelled; ignore completion after account/scope changes.
    let active = true;
    setRoles(null);
    instance
      .acquireTokenSilent({ account, scopes: [config.apiScope] })
      .then((result) => {
        if (active) {
          track('portal_bootstrap', { action: 'authentication', outcome: 'success' });
          setRoles(tokenRoles(result.accessToken));
          setInteractionRequired(false);
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

  if (!account || roles === null) {
    return (
      <main className="welcome">
        <div className="welcome-card">
          <h1>AI gateway administration</h1>
          <p>Manage application budgets, model prices, usage and rate-limit decisions.</p>
          <Badge appearance="outline" color="informative">
            {config.cloud === 'government' ? 'Azure Government' : 'Azure Commercial'}
          </Badge>
          {error && (
            <MessageBar intent="error" role="alert">
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          {restoring || inProgress !== InteractionStatus.None ? (
            <Spinner label="Completing secure sign-in…" />
          ) : (
            <Button appearance="primary" size="large" onClick={() => void signIn()}>
              {interactionRequired ? 'Authorize API access' : 'Sign in with Microsoft'}
            </Button>
          )}
          <p className="note">
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
      profileGreeting={
        <ProfileGreeting
          name={account.name || account.username}
          cloud={config.cloud}
          getGraphToken={getGraphToken}
        />
      }
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
