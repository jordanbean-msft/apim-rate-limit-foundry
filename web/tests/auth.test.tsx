import { StrictMode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  InteractionRequiredAuthError,
  InteractionStatus,
  type AccountInfo,
} from '@azure/msal-browser';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CloudSession } from '../src/CloudSession';
import type { RuntimeConfig } from '../src/contracts';

const auth = vi.hoisted(() => ({
  instance: {
    getActiveAccount: vi.fn(),
    acquireTokenSilent: vi.fn(),
    loginRedirect: vi.fn(),
    logoutRedirect: vi.fn(),
  },
  accounts: [] as AccountInfo[],
  inProgress: 'none' as InteractionStatus,
}));
vi.mock('@azure/msal-react', () => ({ useMsal: () => auth }));
vi.mock('../src/Portal', () => ({
  Portal: ({ identity, onSignOut }: { identity: string; onSignOut: () => void }) => (
    <div>
      Authorized {identity}
      <button onClick={onSignOut}>Sign out</button>
    </div>
  ),
}));
vi.mock('../src/components/ProfileGreeting', () => ({ ProfileGreeting: () => null }));

const config: RuntimeConfig = {
  cloud: 'commercial',
  tenantId: '11111111-1111-1111-1111-111111111111',
  clientId: '22222222-2222-2222-2222-222222222222',
  apiAudience: 'api://api',
  apiScope: 'api://api/access_as_user',
  apiBaseUrl: '/api',
  apiProxyEnabled: true,
  platformAuthEnabled: true,
  demoMode: false,
};
const account = {
  homeAccountId: 'remembered',
  localAccountId: 'remembered',
  environment: 'login.microsoftonline.com',
  tenantId: config.tenantId,
  username: 'remembered@example.test',
  name: 'Remembered account',
} satisfies AccountInfo;

beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  auth.accounts = [];
  auth.inProgress = InteractionStatus.None;
  auth.instance.getActiveAccount.mockReturnValue(null);
  auth.instance.loginRedirect.mockResolvedValue(undefined);
  auth.instance.logoutRedirect.mockResolvedValue(undefined);
  auth.instance.acquireTokenSilent.mockResolvedValue({
    accessToken: `header.${btoa(JSON.stringify({ roles: ['RateLimit.Reader'] }))}.signature`,
  });
});

describe('remembered portal sessions', () => {
  it('authorizes a remembered active account silently and preserves explicit logout', async () => {
    auth.accounts = [{ ...account, name: 'Other account' }, account];
    auth.instance.getActiveAccount.mockImplementation(() => ({ ...account }));
    const view = render(<CloudSession config={config} />);
    expect(await screen.findByText('Authorized Remembered account')).toBeInTheDocument();
    expect(auth.instance.acquireTokenSilent).toHaveBeenCalledWith({
      account,
      scopes: [config.apiScope],
    });
    expect(auth.instance.acquireTokenSilent).toHaveBeenCalledOnce();
    expect(auth.instance.loginRedirect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(auth.instance.logoutRedirect).toHaveBeenCalledWith({ account });
    auth.accounts = [];
    auth.instance.getActiveAccount.mockReturnValue(null);
    view.rerender(<CloudSession config={config} />);
    expect(screen.getByRole('button', { name: 'Sign in with Microsoft' })).toBeInTheDocument();
    expect(auth.instance.loginRedirect).not.toHaveBeenCalled();
  });

  it('reuses native Entra SSO once, including across redirect remounts and StrictMode', async () => {
    const view = render(
      <StrictMode>
        <CloudSession config={config} />
      </StrictMode>,
    );
    await waitFor(() => expect(auth.instance.loginRedirect).toHaveBeenCalledOnce());
    expect(auth.instance.loginRedirect).toHaveBeenCalledWith({
      scopes: [config.apiScope],
      account: undefined,
    });
    view.unmount();
    render(<CloudSession config={config} />);
    expect(auth.instance.loginRedirect).toHaveBeenCalledOnce();
    expect(auth.instance.acquireTokenSilent).not.toHaveBeenCalled();
  });

  it('falls back to explicit retry when automatic SSO fails without redirecting in a loop', async () => {
    auth.instance.loginRedirect.mockRejectedValueOnce(
      new Error('Browser or tenant requires interaction'),
    );
    render(<CloudSession config={config} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in could not start');
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with Microsoft' }));
    await waitFor(() => expect(auth.instance.loginRedirect).toHaveBeenCalledTimes(2));
  });

  it('does not redirect local development or bypass required API authorization', async () => {
    const view = render(<CloudSession config={{ ...config, platformAuthEnabled: false }} />);
    expect(auth.instance.loginRedirect).not.toHaveBeenCalled();
    auth.accounts = [account];
    auth.instance.acquireTokenSilent.mockRejectedValue(
      new InteractionRequiredAuthError('interaction_required'),
    );
    view.rerender(<CloudSession config={{ ...config, platformAuthEnabled: false }} />);
    expect(await screen.findByRole('button', { name: 'Authorize API access' })).toBeInTheDocument();
    expect(screen.queryByText(/Authorized Remembered/)).not.toBeInTheDocument();
  });
});
