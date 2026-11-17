import type { EditableCollection } from '../contracts';
import type { Page } from '../pages';

export type Severity = 'critical' | 'warning' | 'info' | 'success';

/** Declarative next step; the page that renders the insight decides how to perform it. */
export type InsightAction =
  | { kind: 'navigate'; page: Page }
  | { kind: 'create'; collection: EditableCollection }
  | { kind: 'edit'; collection: EditableCollection; id: string }
  | { kind: 'custom'; id: 'retry' | 'shorter-range' | 'wider-range' };

export interface Insight {
  id: string;
  severity: Severity;
  /** What is happening, stated as a fact. */
  title: string;
  /** Why it matters and what to do about it. */
  detail: string;
  action?: { label: string; target: InsightAction };
}

const rank: Record<Severity, number> = { critical: 0, warning: 1, info: 2, success: 3 };

/** Most urgent first; the sort is stable so producers can pre-order within a severity. */
export function sortInsights(insights: Insight[]): Insight[] {
  return [...insights].sort((left, right) => rank[left.severity] - rank[right.severity]);
}

export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

/** First few names for a sentence, with the remainder summarized. */
export function listNames(items: string[], shown = 3): string {
  return (
    items.slice(0, shown).join(', ') +
    (items.length > shown ? ` and ${items.length - shown} more` : '')
  );
}

type Step = NonNullable<Insight['action']>;

export const navigateTo = (label: string, page: Page): Step => ({
  label,
  target: { kind: 'navigate', page },
});
export const createRecord = (label: string, collection: EditableCollection): Step => ({
  label,
  target: { kind: 'create', collection },
});
export const editRecord = (label: string, collection: EditableCollection, id: string): Step => ({
  label,
  target: { kind: 'edit', collection, id },
});
export const customStep = (label: string, id: 'retry' | 'shorter-range' | 'wider-range'): Step => ({
  label,
  target: { kind: 'custom', id },
});
