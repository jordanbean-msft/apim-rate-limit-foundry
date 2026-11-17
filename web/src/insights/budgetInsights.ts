import type { Assignment, Budget, BudgetStatus, Organization } from '../contracts';
import { levelLabels, modelLabel, subjectName } from '../components/budgetLabels';
import { WARNING_RATIO, budgetRatio, percentLabel } from '../components/budgetMath';
import { microUsd } from '../format';
import {
  createRecord,
  editRecord,
  listNames,
  navigateTo,
  plural,
  sortInsights,
  type Insight,
} from './types';

export interface BudgetContext {
  status: BudgetStatus[];
  /** Configuration is only available to administrators; readers see status alone. */
  budgets?: Budget[];
  organizations?: Organization[];
  assignments?: Assignment[];
  admin: boolean;
}

function monthBounds(month: string): { start: number; end: number } {
  const [year, monthNumber] = month.split('-').map(Number);
  return { start: Date.UTC(year, monthNumber - 1, 1), end: Date.UTC(year, monthNumber, 1) };
}

function shortDate(time: number): string {
  return new Date(time).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

function describe(item: BudgetStatus, context: BudgetContext): string {
  const base = context.admin
    ? subjectName(item, context.organizations ?? [], context.assignments ?? [])
    : item.name;
  return item.model === '*' ? base : `${base} (${modelLabel(item.model)})`;
}

function statusInsights(context: BudgetContext): Insight[] {
  const insights: Insight[] = [];
  const ranked = [...context.status].sort(
    (left, right) =>
      budgetRatio(right.spent_micro_usd, right.limit_micro_usd) -
      budgetRatio(left.spent_micro_usd, left.limit_micro_usd),
  );
  for (const item of ranked) {
    const ratio = budgetRatio(item.spent_micro_usd, item.limit_micro_usd);
    const level = levelLabels[item.subject_type].toLowerCase();
    const name = describe(item, context);
    const { end } = monthBounds(item.month);
    const configured = context.budgets?.some((budget) => budget.id === item.budget_id);
    const action = context.admin
      ? configured
        ? editRecord(ratio >= 1 ? 'Raise limit' : 'Review limit', 'budgets', item.budget_id)
        : navigateTo('Open budgets', 'budgets')
      : navigateTo('See where spend went', 'usage');
    const amounts = `${microUsd(item.spent_micro_usd)} of ${microUsd(item.limit_micro_usd)} used`;
    const owner = context.admin
      ? 'Raise the limit if this spend is expected, or ask the owner to reduce usage.'
      : 'Ask your administrator to raise the limit, or reduce usage until it resets.';
    if (ratio >= 1) {
      insights.push({
        id: `limit-${item.budget_id}`,
        severity: 'critical',
        title: `${name} has reached its monthly ${level} limit`,
        detail: `${amounts}. New requests counted against this ${level} budget are denied until it resets on ${shortDate(end)}. ${owner}`,
        action,
      });
    } else if (ratio >= WARNING_RATIO) {
      insights.push({
        id: `near-${item.budget_id}`,
        severity: 'warning',
        title: `${name} is at ${percentLabel(ratio)} of its monthly ${level} limit`,
        detail: `${amounts}, ${microUsd(item.remaining_micro_usd)} remaining. ${owner}`,
        action,
      });
    }
  }
  return insights;
}

function coverageInsights(context: BudgetContext): Insight[] {
  const { budgets, organizations, assignments } = context;
  if (!budgets || !organizations || !assignments) return [];
  if (!budgets.length)
    return [
      {
        id: 'no-budgets',
        severity: 'warning',
        title: 'No budgets are configured',
        detail:
          'Spend is not capped in dollars. Start with a department budget, then add team and user budgets beneath it.',
        action: createRecord('Create a budget', 'budgets'),
      },
    ];
  const covered = (type: Budget['subject_type'], id: string) =>
    budgets.some(
      (budget) => budget.enabled && budget.subject_type === type && budget.subject_id === id,
    );
  const insights: Insight[] = [];
  const gaps: {
    type: Budget['subject_type'];
    severity: 'warning' | 'info';
    items: string[];
    singular: string;
    consequence: string;
  }[] = [
    {
      type: 'department',
      severity: 'warning',
      singular: 'department',
      items: organizations
        .filter(
          (item) => item.enabled && item.kind === 'department' && !covered('department', item.id),
        )
        .map((item) => item.name),
      consequence: 'Their total spend is not capped.',
    },
    {
      type: 'team',
      severity: 'warning',
      singular: 'team',
      items: organizations
        .filter((item) => item.enabled && item.kind === 'team' && !covered('team', item.id))
        .map((item) => item.name),
      consequence: 'Only their department cap limits them.',
    },
    {
      type: 'user',
      severity: 'info',
      singular: 'user',
      items: assignments
        .filter((item) => item.enabled && !covered('user', item.principal_id))
        .map((item) => item.display_label || item.principal_id),
      consequence: 'They are limited only by their team and department caps.',
    },
  ];
  for (const gap of gaps) {
    if (!gap.items.length) continue;
    insights.push({
      id: `gap-${gap.type}`,
      severity: gap.severity,
      title: `${plural(gap.items.length, gap.singular)} without a monthly budget`,
      detail: `${listNames(gap.items)}. ${gap.consequence} Create a ${gap.type} budget to set a dollar limit.`,
      action: createRecord(`Create ${gap.type} budget`, 'budgets'),
    });
  }
  const disabled = budgets.filter((budget) => !budget.enabled);
  if (disabled.length)
    insights.push({
      id: 'disabled-budgets',
      severity: 'info',
      title: `${plural(disabled.length, 'budget')} disabled`,
      detail: `${listNames(disabled.map((budget) => budget.name))}. Disabled budgets are not enforced. Re-enable them or delete them if retired.`,
      action: navigateTo('Review budgets', 'budgets'),
    });
  return [...insights, ...hierarchyInsights(budgets, organizations, assignments)];
}

/** A child limit above its parent's (same model) can never bind: the parent denies first. */
function hierarchyInsights(
  budgets: Budget[],
  organizations: Organization[],
  assignments: Assignment[],
): Insight[] {
  const enabled = budgets.filter((budget) => budget.enabled);
  const parentOf = (budget: Budget): { type: Budget['subject_type']; id: string } | null => {
    if (budget.subject_type === 'user') {
      const team = assignments.find((item) => item.principal_id === budget.subject_id)?.team_id;
      return team ? { type: 'team', id: team } : null;
    }
    if (budget.subject_type === 'team') {
      const department = organizations.find((item) => item.id === budget.subject_id)?.department_id;
      return department ? { type: 'department', id: department } : null;
    }
    return null;
  };
  const insights: Insight[] = [];
  for (const budget of enabled) {
    const parent = parentOf(budget);
    const cap = parent
      ? enabled.find(
          (item) =>
            item.subject_type === parent.type &&
            item.subject_id === parent.id &&
            item.model === budget.model,
        )
      : undefined;
    if (cap && budget.limit_micro_usd > cap.limit_micro_usd)
      insights.push({
        id: `exceeds-parent-${budget.id}`,
        severity: 'info',
        title: `${budget.name} is set above its ${cap.subject_type} cap`,
        detail: `${microUsd(budget.limit_micro_usd)} exceeds ${cap.name} at ${microUsd(cap.limit_micro_usd)}, so the ${cap.subject_type} limit will deny requests first. Lower this limit or raise the ${cap.subject_type} cap.`,
        action: editRecord('Review limit', 'budgets', budget.id),
      });
  }
  return insights;
}

/** Budget-health recommendations ordered by urgency: breached, near limit, pacing, coverage gaps. */
export function budgetInsights(context: BudgetContext): Insight[] {
  const insights = [...statusInsights(context), ...coverageInsights(context)];
  if (!context.admin && !context.status.length)
    insights.push({
      id: 'no-applicable-budget',
      severity: 'info',
      title: 'No monthly budget applies to your account',
      detail: 'Your usage is not capped in dollars.',
    });
  return sortInsights(insights);
}
