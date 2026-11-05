import { PublicClientApplication } from '@azure/msal-browser';
import type { Role, RuntimeConfig } from './contracts';

const hosts = {
  commercial: 'login.microsoftonline.com',
  government: 'login.microsoftonline.us',
};

export function createMsal(config: RuntimeConfig): PublicClientApplication {
  if (!Object.hasOwn(hosts, config.cloud)) throw new Error('Unsupported Azure cloud');
  const host = hosts[config.cloud];
  return new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: `https://${host}/${config.tenantId}`,
      knownAuthorities: [host],
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
      navigateToLoginRequestUrl: false,
    },
    cache: { cacheLocation: 'sessionStorage' },
  });
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
