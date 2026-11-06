// @vitest-environment node
import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import { observeRequest, writeLog } from '../server/logging.mjs';

describe('safe HTTP lifecycle logging', () => {
  it('emits one aborted outcome even if finish follows close, ignoring injected correlation headers', () => {
    const logger = vi.fn();
    const res = Object.assign(new EventEmitter(), {
      setHeader: vi.fn(),
      statusCode: 200,
      writableFinished: false,
    });
    observeRequest(
      { method: 'PRIVATE-METHOD', headers: { 'x-correlation-id': 'private-user' } },
      res,
      logger,
    );
    res.emit('close');
    res.emit('finish');
    expect(logger).toHaveBeenCalledOnce();
    expect(logger).toHaveBeenCalledWith(
      expect.objectContaining({
        event: 'portal_request',
        method: 'OTHER',
        status: 0,
        outcome: 'aborted',
        errorCategory: 'connection_closed',
      }),
    );
    expect(JSON.stringify(logger.mock.calls)).not.toContain('private');
  });
  it('writes JSON and tolerates console capture failure', () => {
    const consoleLog = vi.spyOn(console, 'info');
    writeLog({ event: 'portal_server_error', errorCategory: 'listen_error' });
    expect(JSON.parse(consoleLog.mock.calls[0][0])).toMatchObject({
      event: 'portal_server_error',
      errorCategory: 'listen_error',
      timestamp: expect.any(String),
    });
    consoleLog.mockImplementation(() => {
      throw new Error('sink unavailable');
    });
    expect(() => writeLog({ event: 'portal_started' })).not.toThrow();
  });
});
