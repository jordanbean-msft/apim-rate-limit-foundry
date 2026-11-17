import type { Assignment, BudgetStatus, Organization } from '../contracts';

export const levelOrder: BudgetStatus['subject_type'][] = ['department', 'team', 'user'];

export const levelLabels: Record<BudgetStatus['subject_type'], string> = {
  department: 'Department',
  team: 'Team',
  user: 'User',
};

/** Resolve optional authorized labels while retaining stable subject IDs when metadata is absent. */
export function subjectName(
  status: BudgetStatus,
  organizations: Organization[],
  assignments: Assignment[],
): string {
  if (status.subject_type === 'user') {
    const assignment = assignments.find((item) => item.principal_id === status.subject_id);
    return assignment?.display_label ?? status.subject_id;
  }
  return organizations.find((item) => item.id === status.subject_id)?.name ?? status.subject_id;
}

/** Order budgets department → team → user so the hierarchy reads top-down. */
export function sortByLevel(status: BudgetStatus[]): BudgetStatus[] {
  return [...status].sort(
    (left, right) =>
      levelOrder.indexOf(left.subject_type) - levelOrder.indexOf(right.subject_type) ||
      left.name.localeCompare(right.name),
  );
}

export function modelLabel(model: string): string {
  return model === '*' ? 'All models' : model;
}
