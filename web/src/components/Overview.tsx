import { Button } from '@fluentui/react-components';
import type { Assignment, BudgetStatus, Collection, Organization, UsageRecord } from '../contracts';
import { BudgetCards } from './BudgetCards';
import { WARNING_RATIO, budgetRatio } from './budgetMath';
import { BudgetStatusNote } from './BudgetStatusTable';
import { StatCard } from './StatCard';
import { Unavailable } from './Unavailable';
import { UsageTable } from './UsageTable';

/** Summarize authorized loaded records, keeping live status and persisted usage failures separate. */
export function Overview({
  status,
  usage,
  organizations,
  assignments,
  errors,
  loading,
  navigate,
}: {
  status: BudgetStatus[];
  usage: UsageRecord[];
  organizations: Organization[];
  assignments: Assignment[];
  errors: Partial<Record<Collection | 'budgetStatus', string>>;
  loading: boolean;
  navigate: (page: 'budgets' | 'usage') => void;
}) {
  // Count event outcomes, not provider requests inferred from HTTP success or budget admission.
  const actualCount = usage.filter((record) => record.status === 'actual').length;
  const unknownCount = usage.filter((record) => record.status === 'usage_unknown').length;
  const nearLimit = status.filter(
    (item) => budgetRatio(item.spent_micro_usd, item.limit_micro_usd) >= WARNING_RATIO,
  ).length;
  return (
    <>
      <section className="stat-grid" aria-label="Monthly usage summary">
        <StatCard
          label="Budgets in scope"
          value={errors.budgetStatus ? '—' : status.length}
          note="Department, team and user limits"
        />
        <StatCard
          label="At or above 80% of limit"
          value={errors.budgetStatus ? '—' : nearLimit}
          note="Budgets close to denying requests"
        />
        <StatCard
          label="Finalized requests"
          value={errors.usage ? '—' : actualCount}
          note="Actual provider-reported usage"
        />
        <StatCard
          label="Unknown usage"
          value={errors.usage ? '—' : unknownCount}
          note="Streams without reported usage"
        />
      </section>
      <section className="page-section">
        <div className="section-heading">
          <h2>Month-to-date budgets</h2>
          <Button appearance="subtle" size="small" onClick={() => navigate('budgets')}>
            View all budgets
          </Button>
        </div>
        {errors.budgetStatus ? (
          <Unavailable what="Budget status" />
        ) : !status.length && !loading ? (
          <p className="empty-inline">No configured monthly budgets apply to this account.</p>
        ) : (
          <BudgetCards status={status} organizations={organizations} assignments={assignments} />
        )}
        <BudgetStatusNote />
      </section>
      <section className="page-section">
        <div className="section-heading">
          <h2>Latest usage</h2>
          <Button appearance="subtle" size="small" onClick={() => navigate('usage')}>
            View all usage
          </Button>
        </div>
        <div className="surface">
          {errors.usage ? <Unavailable what="Usage" /> : <UsageTable records={usage.slice(0, 5)} />}
        </div>
      </section>
    </>
  );
}
