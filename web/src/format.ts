/** Format safe integer micro-USD exactly, preserving sub-cent values and unknown data. */
export function microUsd(value: unknown): string {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    return 'Not reported';
  }
  // Split whole dollars and the six-digit remainder without floating-point currency rounding.
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

/** Display valid timestamps in UTC and retain unparseable source values for diagnosis. */
export function utcTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? value
    : `${date.toISOString().replace('T', ' ').replace('.000Z', '')} UTC`;
}

/** Narrow unknown data to a non-array object without asserting any field-level schema. */
export function objectValue(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** Render scalar text without stringifying arbitrary response objects. */
export function text(value: unknown, fallback = 'Not reported'): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}
