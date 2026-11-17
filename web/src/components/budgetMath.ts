import { percent } from '../numbers';

export const WARNING_RATIO = 0.8;

/** Fraction of the monthly limit already consumed; zero-limit budgets are treated as exhausted. */
export function budgetRatio(spentMicroUsd: number, limitMicroUsd: number): number {
  if (limitMicroUsd <= 0) return 1;
  return Math.max(0, spentMicroUsd / limitMicroUsd);
}

/** Compact percentage that never rounds a non-zero spend down to a misleading 0%. */
export function percentLabel(ratio: number): string {
  if (ratio <= 0) return '0%';
  if (ratio < 0.01) return '<1%';
  return `${percent(ratio)}%`;
}
