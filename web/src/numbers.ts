/** Sum a numeric projection of each item; the caller decides how nulls count. */
export function sumBy<T>(items: readonly T[], value: (item: T) => number): number {
  return items.reduce((total, item) => total + value(item), 0);
}

/** Whole-number percentage of a ratio. */
export function percent(ratio: number): number {
  return Math.round(ratio * 100);
}
