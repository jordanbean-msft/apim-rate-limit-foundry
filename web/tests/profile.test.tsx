import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProfileGreeting } from '../src/components/ProfileGreeting';
import * as telemetry from '../src/telemetry';

afterEach(() => vi.unstubAllGlobals());

function renderProfile(
  getGraphToken: () => Promise<string>,
  cloud: 'commercial' | 'government' = 'commercial',
) {
  return render(
    <FluentProvider theme={webLightTheme}>
      <ProfileGreeting name="Alex Brown" cloud={cloud} getGraphToken={getGraphToken} />
    </FluentProvider>,
  );
}

describe('Graph profile greeting', () => {
  it('records only fixed Graph dependency operations and never forwards tracing headers', async () => {
    const finish = vi.fn();
    const begin = vi.spyOn(telemetry, 'beginDependency').mockReturnValue({
      traceparent: '00-safe-but-must-not-be-sent',
      finish,
    });
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 403 }))
      .mockRejectedValueOnce(new Error('private Graph error'));
    vi.stubGlobal('fetch', fetchImpl);
    const view = renderProfile(async () => 'private-token');
    await waitFor(() => expect(finish).toHaveBeenCalledTimes(2));
    expect(begin.mock.calls).toEqual([['graph_profile'], ['graph_photo']]);
    expect(finish.mock.calls).toEqual([
      [403, 'failure'],
      [0, 'failure'],
    ]);
    for (const [, options] of fetchImpl.mock.calls) {
      expect(Object.keys(options.headers)).toEqual(['Authorization']);
      expect(options.redirect).toBe('error');
    }
    expect(JSON.stringify([...begin.mock.calls, ...finish.mock.calls])).not.toContain('private');
    view.unmount();
  });

  it('uses the cloud-specific Graph token for profile/photo and revokes the in-memory photo URL', async () => {
    const getGraphToken = vi.fn().mockResolvedValue('distinct-graph-token');
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ displayName: 'Alex Graph' }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Blob(['private-photo-bytes'], { type: 'image/png' }), {
          headers: { 'Content-Type': 'image/png' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.fn().mockReturnValue('blob:profile-photo');
    const revokeObjectURL = vi.fn();
    vi.spyOn(URL, 'createObjectURL').mockImplementation(createObjectURL);
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(revokeObjectURL);

    const view = renderProfile(getGraphToken, 'government');
    expect(await screen.findByText('Howdy Alex Graph!')).toBeInTheDocument();
    await waitFor(() => expect(view.container.querySelector('img')).not.toBeNull());
    expect(view.container.querySelector('img')).toHaveAttribute('src', 'blob:profile-photo');
    expect(getGraphToken).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [url, options] of fetchMock.mock.calls) {
      expect(url).toMatch(/^https:\/\/graph\.microsoft\.us\/v1\.0\/me/);
      expect(options).toMatchObject({
        headers: { Authorization: 'Bearer distinct-graph-token' },
        credentials: 'omit',
        cache: 'no-store',
      });
    }
    view.unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:profile-photo');
  });

  it('falls back to initials when Graph consent or the photo is unavailable', async () => {
    const getGraphToken = vi.fn().mockRejectedValue(new Error('consent denied'));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const denied = renderProfile(getGraphToken);
    expect(await screen.findByText('Howdy Alex Brown!')).toBeInTheDocument();
    expect(screen.getByText('AB')).toBeInTheDocument();
    expect(denied.container.querySelector('img')).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    denied.unmount();

    getGraphToken.mockResolvedValue('graph-token');
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 403 }))
      .mockResolvedValueOnce(new Response(null, { status: 404 }));
    const fallback = renderProfile(getGraphToken);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'https://graph.microsoft.com/v1.0/me?$select=displayName',
      'https://graph.microsoft.com/v1.0/me/photo/$value',
    ]);
    expect(fallback.getByText('AB')).toBeInTheDocument();
    expect(fallback.container.querySelector('img')).not.toBeInTheDocument();
    fallback.unmount();
  });
});
