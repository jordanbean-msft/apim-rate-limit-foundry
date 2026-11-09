export function microUsd(value: unknown): string {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    return 'Not reported';
  }
  const units = BigInt(value);
  const absolute = units < 0n ? -units : units;
  const whole = new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 0,
  }).format(Number(absolute / 1_000_000n));
  const fraction = (absolute % 1_000_000n)
    .toString()
    .padStart(6, '0')
    .replace(/0+$/, '')
    .padEnd(2, '0');
  return `${units < 0n ? '-' : ''}$${whole}.${fraction}`;
}

export function utcTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : `${date.toISOString().replace('T', ' ').replace('.000Z', '')} UTC`;
}

export function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function text(value: unknown, fallback = 'Not reported'): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}
