import type { Assignment, Model, Organization, Price } from '../contracts';
import {
  createRecord,
  editRecord,
  listNames,
  navigateTo,
  plural,
  sortInsights,
  type Insight,
} from './types';

/** Models need exactly one price card for their pinned version or spend cannot be costed. */
export function modelInsights(models: Model[], prices: Price[], admin: boolean): Insight[] {
  if (!models.length)
    return [
      {
        id: 'no-models',
        severity: 'warning',
        title: 'No models are registered',
        detail: 'The gateway inventory is empty, so no model can be called through it.',
      },
    ];
  if (!admin) return [];
  const insights: Insight[] = [];
  const unpriced = models.filter(
    (model) =>
      !prices.some((price) => price.model === model.model && price.version === model.price_version),
  );
  if (unpriced.length)
    insights.push({
      id: 'unpriced-models',
      severity: 'critical',
      title: `${plural(unpriced.length, 'model')} without a price card`,
      detail: `${listNames(unpriced.map((model) => `${model.model} (${model.price_version})`))}. Usage cannot be costed against budgets until a card exists for the pinned version.`,
      action: createRecord('Create price card', 'prices'),
    });
  const ambiguous = models.filter(
    (model) =>
      prices.filter((price) => price.model === model.model && price.version === model.price_version)
        .length > 1,
  );
  if (ambiguous.length)
    insights.push({
      id: 'ambiguous-prices',
      severity: 'warning',
      title: `${plural(ambiguous.length, 'model')} with duplicate price cards`,
      detail: `${listNames(ambiguous.map((model) => model.model))}. Delete the extra cards so one version is unambiguous.`,
      action: navigateTo('Review price cards', 'prices'),
    });
  return sortInsights(insights);
}

/** Flag price cards that are unused or whose rates look wrong. */
export function priceInsights(prices: Price[], models: Model[]): Insight[] {
  const insights: Insight[] = [];
  const free = prices.filter(
    (price) => Number(price.input_per_million) === 0 || Number(price.output_per_million) === 0,
  );
  for (const price of free)
    insights.push({
      id: `free-${price.id}`,
      severity: 'warning',
      title: `${price.model} ${price.version} has a $0 input or output rate`,
      detail:
        'Requests priced with this card cost nothing, so they never consume a budget. Set the real rate unless this is intentional.',
      action: editRecord('Edit price card', 'prices', price.id),
    });
  for (const price of prices.filter(
    (item) => Number(item.cached_input_per_million) > Number(item.input_per_million),
  ))
    insights.push({
      id: `cache-rate-${price.id}`,
      severity: 'warning',
      title: `${price.model} ${price.version} charges more for cached input than uncached`,
      detail: 'Cached input is normally cheaper. Check the rates for a swapped value.',
      action: editRecord('Edit price card', 'prices', price.id),
    });
  const unused = prices.filter(
    (price) =>
      !models.some((model) => model.model === price.model && model.price_version === price.version),
  );
  if (unused.length)
    insights.push({
      id: 'unused-prices',
      severity: 'info',
      title: `${plural(unused.length, 'price card')} not pinned by any model`,
      detail: `${listNames(unused.map((price) => `${price.model} ${price.version}`))}. They are not used for pricing new requests.`,
      action: navigateTo('Check model pins', 'models'),
    });
  return sortInsights(insights);
}

/** Hierarchy and membership checks that decide which budgets a request resolves to. */
export function organizationInsights(
  organizations: Organization[],
  assignments: Assignment[],
): Insight[] {
  const insights: Insight[] = [];
  const enabledDepartments = organizations.filter(
    (item) => item.kind === 'department' && item.enabled,
  );
  const teams = organizations.filter((item) => item.kind === 'team' && item.enabled);
  const orphaned = teams.filter(
    (team) => !enabledDepartments.some((department) => department.id === team.department_id),
  );
  for (const team of orphaned)
    insights.push({
      id: `orphan-${team.id}`,
      severity: 'warning',
      title: `Team ${team.name} has no enabled parent department`,
      detail:
        'Its users will not inherit a department budget or chargeback allocation. Choose an enabled department.',
      action: editRecord('Fix team', 'organizations', team.id),
    });
  const empty = teams.filter(
    (team) =>
      !assignments.some((assignment) => assignment.enabled && assignment.team_id === team.id),
  );
  if (empty.length)
    insights.push({
      id: 'empty-teams',
      severity: 'info',
      title: `${plural(empty.length, 'team')} with no assigned users`,
      detail: `${listNames(empty.map((team) => team.name))}. Assign users so their usage is attributed to the team, or disable the team.`,
      action: navigateTo('Assign users', 'assignments'),
    });
  const emptyDepartments = enabledDepartments.filter(
    (department) => !teams.some((team) => team.department_id === department.id),
  );
  if (emptyDepartments.length)
    insights.push({
      id: 'empty-departments',
      severity: 'info',
      title: `${plural(emptyDepartments.length, 'department')} with no teams`,
      detail: `${listNames(emptyDepartments.map((department) => department.name))}. Add a team to start attributing usage, or disable the department.`,
    });
  return sortInsights(insights);
}

/** Assignments only resolve to budgets when their team is enabled and the department matches. */
export function assignmentInsights(
  assignments: Assignment[],
  organizations: Organization[],
): Insight[] {
  const insights: Insight[] = [];
  if (!assignments.length)
    return [
      {
        id: 'no-assignments',
        severity: 'warning',
        title: 'No users are assigned to a team',
        detail:
          'Without an assignment, callers have no team or department, so team and department budgets cannot apply to them. Assign each Entra user to a team.',
        action: createRecord('Create assignment', 'assignments'),
      },
    ];
  for (const assignment of assignments.filter((item) => item.enabled)) {
    const team = organizations.find((item) => item.id === assignment.team_id);
    const label = assignment.display_label || assignment.principal_id;
    if (!team || !team.enabled)
      insights.push({
        id: `team-${assignment.id}`,
        severity: 'critical',
        title: `${label} is assigned to a ${team ? 'disabled' : 'missing'} team`,
        detail:
          'Their requests cannot resolve to a team or department budget. Move them to an enabled team.',
        action: editRecord('Fix assignment', 'assignments', assignment.id),
      });
    else if (team.department_id !== assignment.department_id)
      insights.push({
        id: `department-${assignment.id}`,
        severity: 'warning',
        title: `${label}'s department no longer matches their team`,
        detail: `The team now belongs to ${team.department_id ?? 'no department'}. Save the assignment again to refresh it.`,
        action: editRecord('Fix assignment', 'assignments', assignment.id),
      });
  }
  return sortInsights(insights);
}
