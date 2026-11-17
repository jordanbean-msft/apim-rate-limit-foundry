import { describe, expect, it } from 'vitest';
import type {
  Assignment,
  Budget,
  BudgetStatus,
  ChargebackRow,
  Organization,
  UsageRecord,
} from '../src/contracts';
import { budgetInsights } from '../src/insights/budgetInsights';
import { chargebackInsights } from '../src/insights/chargebackInsights';
import { usageInsights } from '../src/insights/usageInsights';

const MILLION = 1_000_000;
const status = (spent: number, overrides: Partial<BudgetStatus> = {}): BudgetStatus => ({
  budget_id: 'team-budget',
  name: 'Platform monthly',
  subject_type: 'team',
  subject_id: 'platform',
  model: '*',
  limit_micro_usd: 100 * MILLION,
  spent_micro_usd: spent * MILLION,
  remaining_micro_usd: (100 - spent) * MILLION,
  month: '2026-11',
  ...overrides,
});
const budget = (overrides: Partial<Budget> = {}): Budget => ({
  id: 'team-budget',
  tenant_id: 't',
  name: 'Platform monthly',
  subject_type: 'team',
  subject_id: 'platform',
  model: '*',
  limit_micro_usd: 100 * MILLION,
  enabled: true,
  ...overrides,
});
const org = (overrides: Partial<Organization>): Organization => ({
  id: 'platform',
  tenant_id: 't',
  kind: 'team',
  name: 'Platform',
  department_id: 'engineering',
  business_unit: 'Product',
  cost_center: 'CC-1',
  enabled: true,
  ...overrides,
});
const assignment: Assignment = {
  id: 'a1',
  tenant_id: 't',
  principal_id: 'alice',
  team_id: 'platform',
  department_id: 'engineering',
  display_label: 'Alice',
  enabled: true,
};
const midMonth = new Date('2026-11-16T00:00:00Z');

describe('budget insights', () => {
  it('escalates a breached budget with a raise-limit action for administrators', () => {
    const [first] = budgetInsights({
      status: [status(100)],
      budgets: [budget()],
      organizations: [org({})],
      assignments: [],
      admin: true,
    });
    expect(first.severity).toBe('critical');
    expect(first.action).toEqual({
      label: 'Raise limit',
      target: { kind: 'edit', collection: 'budgets', id: 'team-budget' },
    });
  });

  it('gives readers no edit action and points them to usage', () => {
    const [first] = budgetInsights({ status: [status(100)], admin: false });
    expect(first.action?.target).toEqual({ kind: 'navigate', page: 'usage' });
    expect(first.detail).toMatch(/administrator/);
  });

  it('stays quiet while a budget is below 80%', () => {
    expect(budgetInsights({ status: [status(10)], admin: false })).toEqual([]);
  });

  it('flags teams and users without budgets and caps that exceed their parent', () => {
    const insights = budgetInsights({
      status: [status(1)],
      budgets: [
        budget({
          id: 'u',
          subject_type: 'user',
          subject_id: 'alice',
          name: 'Alice',
          limit_micro_usd: 500 * MILLION,
        }),
        budget(),
      ],
      organizations: [
        org({
          id: 'engineering',
          kind: 'department',
          name: 'Engineering',
          department_id: undefined,
        }),
        org({ id: 'research', name: 'Research' }),
        org({}),
      ],
      assignments: [assignment],
      admin: true,
    });
    const ids = insights.map((item) => item.id);
    expect(ids).toContain('gap-department');
    expect(ids).toContain('gap-team');
    expect(ids).toContain('exceeds-parent-u');
    expect(insights.find((item) => item.id === 'gap-team')?.detail).toContain('Research');
  });
});

const usage = (overrides: Partial<UsageRecord>): UsageRecord =>
  ({
    request_id: 'r1',
    model: 'gpt-4o',
    team_id: 'platform',
    status: 'actual',
    input_tokens: 1000,
    cached_input_tokens: 0,
    cost_micro_usd: MILLION,
    ...overrides,
  }) as UsageRecord;

describe('usage insights', () => {
  it('names the latest unknown-usage request and has nothing to say about an empty window', () => {
    expect(usageInsights([], true)).toEqual([]);
    const insights = usageInsights(
      [usage({}), usage({ request_id: 'stream-9', status: 'usage_unknown', cost_micro_usd: null })],
      true,
    );
    expect(insights).toHaveLength(1);
    expect(insights[0].detail).toContain('stream-9');
  });
});

const row = (overrides: Partial<ChargebackRow>): ChargebackRow => ({
  business_unit: 'Product',
  cost_center: 'CC-1',
  department_id: 'engineering',
  team_id: 'platform',
  user_ref: 'u',
  subscription_id: 's',
  model: 'gpt-4o',
  month: '2026-10',
  input_tokens: 1,
  cached_input_tokens: 0,
  output_tokens: 1,
  cost_micro_usd: MILLION,
  unknown_requests: 0,
  ...overrides,
});

describe('chargeback insights', () => {
  it('marks the open month provisional and blocks unallocated rows', () => {
    const insights = chargebackInsights(
      [row({ cost_center: '', unknown_requests: 2 })],
      '2026-11',
      midMonth,
      true,
    );
    const ids = insights.map((item) => item.id);
    expect(ids).toEqual(
      expect.arrayContaining(['open-month', 'unknown-requests', 'missing-cost-center']),
    );
    expect(insights.find((item) => item.id === 'open-month')?.detail).toContain('15 more days');
  });

  it('has nothing to flag for a closed, fully allocated month', () => {
    expect(chargebackInsights([row({})], '2026-10', midMonth, true)).toEqual([]);
  });
});
