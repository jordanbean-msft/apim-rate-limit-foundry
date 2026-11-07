import { EventType, PublicClientApplication, type AuthenticationResult } from '@azure/msal-browser';
import type { Role, RuntimeConfig } from './contracts';

const hosts = {
  commercial: 'login.microsoftonline.com',
  government: 'login.microsoftonline.us',
};

export function createMsal(config: RuntimeConfig): PublicClientApplication {
  if (!Object.hasOwn(hosts, config.cloud)) throw new Error('Unsupported Azure cloud');
  const host = hosts[config.cloud];
  const instance = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: `https://${host}/${config.tenantId}`,
      knownAuthorities: [host],
      redirectUri: window.location.origin,
      postLogoutRedirectUri: config.platformAuthEnabled
        ? `${window.location.origin}/.auth/logout`
        : window.location.origin,
      navigateToLoginRequestUrl: false,
    },
    cache: { cacheLocation: 'localStorage' },
  });
  instance.addEventCallback((event) => {
    if (event.eventType === EventType.LOGIN_SUCCESS) {
      instance.setActiveAccount((event.payload as AuthenticationResult).account);
    }
  });
  return instance;
}

/** Navigation hints only. The API independently validates the token and enforces authorization. */
export function tokenRoles(accessToken: string): Role[] {
  try {
    const encoded = accessToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const claims = JSON.parse(atob(encoded)) as { roles?: unknown };
    return Array.isArray(claims.roles)
      ? claims.roles.filter((role): role is Role =>
          ['RateLimit.Admin', 'RateLimit.Reader', 'RateLimit.Gateway'].includes(role),
        )
      : [];
  } catch {
    return [];
  }
}
