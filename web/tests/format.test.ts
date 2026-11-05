import { describe, expect, it } from 'vitest';
import { microUsd } from '../src/format';

describe('integer microUSD display', () => {
  it('does not round away microUSD at the largest supported budget', () => {
    expect(microUsd(Number.MAX_SAFE_INTEGER)).toBe('$9,007,199,254.740991');
    expect(microUsd(5)).toBe('$0.000005');
    expect(microUsd(-1_230_000)).toBe('-$1.23');
  });

  it('does not present an unsafe or fractional budget as an exact amount', () => {
    expect(microUsd(Number.MAX_SAFE_INTEGER + 1)).toBe('Not reported');
    expect(microUsd(0.5)).toBe('Not reported');
    expect(microUsd('25000000')).toBe('Not reported');
  });
});
