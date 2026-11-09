import { Badge, Button } from '@fluentui/react-components';
import {
  DataTrendingRegular,
  ReceiptMoneyRegular,
  ShieldCheckmarkRegular,
} from '@fluentui/react-icons';
import type { Assignment, BudgetStatus, Collection, Organization, UsageRecord } from '../contracts';
import { BudgetStatusTable } from './BudgetStatusTable';
import { UsageTable } from './UsageTable';

function Stat({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: string | number;
  note: string;
  icon: React.ReactNode;
}) {
  return (
    <article className="stat-card">
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <div className="stat-value">{value}</div>
      <p>{note}</p>
    </article>
  );
}

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
  navigate: (page: 'budgets' | 'usage' | 'chargeback') => void;
}) {
  const actualCount = usage.filter((record) => record.status === 'actual').length;
  const unknownCount = usage.filter((record) => record.status === 'usage_unknown').length;
  return (
    <>
      <section className="stat-grid" aria-label="Monthly usage summary">
        <Stat
          label="Applicable monthly budgets"
          value={errors.budgetStatus ? '—' : status.length}
          note="User, team and department limits"
          icon={<ShieldCheckmarkRegular />}
        />
        <Stat
          label="Finalized usage records"
          value={errors.usage ? '—' : actualCount}
          note="Actual provider-reported usage"
          icon={<DataTrendingRegular />}
        />
        <Stat
          label="Unknown stream usage"
          value={errors.usage ? '—' : unknownCount}
          note="Never represented as zero-cost"
          icon={<ReceiptMoneyRegular />}
        />
      </section>
      <section className="surface">
        <div className="section-heading">
          <h2>Month-to-date budget status</h2>
          <Button appearance="subtle" size="small" onClick={() => navigate('budgets')}>
            View budgets
          </Button>
        </div>
        {errors.budgetStatus ? (
          <p className="empty-inline">Budget status is unavailable. Refresh to retry.</p>
        ) : (
          <BudgetStatusTable
            status={status}
            organizations={organizations}
            assignments={assignments}
            loading={loading}
          />
        )}
      </section>
      <section className="surface">
        <div className="section-heading">
          <div>
            <h2>Enforcement and accounting</h2>
            <p className="muted">
              Monthly spend is checked before a request. Provider-reported actual cost is recorded
              after completion; every configured level is enforced.
            </p>
          </div>
          <Badge appearance="tint" color="warning">
            Soft cap
          </Badge>
        </div>
        <p>
          Concurrent in-flight requests may overshoot a budget. Once actual spend reaches the limit,
          subsequent requests are denied. This is not a strict no-overshoot financial control.
        </p>
        <div className="row-actions">
          <Button appearance="subtle" onClick={() => navigate('usage')}>
            View usage
          </Button>
          <Button appearance="subtle" onClick={() => navigate('chargeback')}>
            Open chargeback
          </Button>
        </div>
      </section>
      <section className="surface">
        <div className="section-heading">
          <h2>Latest authorized usage</h2>
          <Button appearance="subtle" size="small" onClick={() => navigate('usage')}>
            Explore usage
          </Button>
        </div>
        {errors.usage ? (
          <p className="empty-inline">Usage is unavailable. Refresh to retry.</p>
        ) : (
          <UsageTable records={usage.slice(0, 5)} />
        )}
      </section>
    </>
  );
}
