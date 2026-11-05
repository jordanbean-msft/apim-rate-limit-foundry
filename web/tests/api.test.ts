import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApi } from '../src/api';
import { tokenRoles } from '../src/auth';

afterEach(() => vi.unstubAllGlobals());

describe('authenticated API', () => {
  it('sends an access token and never an arbitrary consumer principal filter', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('[]'));
    vi.stubGlobal('fetch', fetch);
    const getToken = vi.fn().mockResolvedValue('api-access-token');
    const api = createApi('https://gateway.example/portal', getToken);
    await api.list('usage');
    expect(fetch).toHaveBeenCalledWith(
      'https://gateway.example/portal/usage',
      expect.objectContaining({
        headers: { Authorization: 'Bearer api-access-token' },
        credentials: 'omit',
      }),
    );
    expect(getToken).toHaveBeenCalledOnce();
  });

  it.each([401, 403, 500])(
    'surfaces HTTP %i failures instead of returning demo records',
    async (status) => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status })));
      await expect(
        createApi('https://api.example/api', async () => 'token').list('policies'),
      ).rejects.toMatchObject({ status });
    },
  );

  it('rejects an invalid collection contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"items":[]}')));
    await expect(
      createApi('https://api.example/api', async () => 'token').list('usage'),
    ).rejects.toThrow('invalid collection response');
  });

  it('fails closed when no portal roles are present in an access token', () => {
    const token = (claims: unknown) => `header.${btoa(JSON.stringify(claims))}.signature`;
    expect(tokenRoles(token({ roles: ['RateLimit.Reader', 'unknown'] }))).toEqual([
      'RateLimit.Reader',
    ]);
    expect(tokenRoles(token({}))).toEqual([]);
    expect(tokenRoles('invalid')).toEqual([]);
  });
});
