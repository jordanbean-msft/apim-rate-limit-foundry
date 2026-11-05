import { Badge, Button } from '@fluentui/react-components';
import {
  ArrowClockwiseRegular,
  DataTrendingRegular,
  ShieldCheckmarkRegular,
  WarningRegular,
} from '@fluentui/react-icons';
import { isDenial, isEstimated } from '../accounting';
import type { Collection, LedgerRecord, Policy } from '../contracts';
import { objectValue, services } from '../format';
import { LedgerTable } from './LedgerTable';
import { PolicyLimit } from './PolicyLimit';

function Stat({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: React.ReactNode;
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

function ServiceActivity({ usage, unavailable }: { usage: LedgerRecord[]; unavailable: boolean }) {
  return (
    <section className="surface service-activity" aria-label="Usage events by service">
      <div className="section-heading">
        <h2>Service activity</h2>
        <span className="fine-print">Returned events · including denials · not spend</span>
      </div>
      {unavailable ? (
        <p className="empty-inline">Usage is unavailable. Refresh to retry.</p>
      ) : (
        <div className="service-bars">
          {Object.entries(services).map(([service, label]) => {
            const count = usage.filter(
              (record) => objectValue(record.data.request).service === service,
            ).length;
            return (
              <div key={service}>
                <div className="service-bar-label">
                  <span>{label}</span>
                  <strong>{count} events</strong>
                </div>
                <div className="service-track" aria-hidden="true">
                  <div
                    className={`service-fill ${service}`}
                    style={{ width: `${usage.length ? (count / usage.length) * 100 : 0}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function Overview({
  policies,
  usage,
  errors,
  loading,
  navigate,
}: {
  policies: Policy[];
  usage: LedgerRecord[];
  errors: Partial<Record<Collection, string>>;
  loading: boolean;
  navigate: (page: 'policies' | 'usage' | 'reconciliation') => void;
}) {
  return (
    <>
      <section className="stat-grid" aria-label="Activity summary">
        <Stat
          label="Active policies"
          value={errors.policies ? '—' : policies.filter((policy) => policy.enabled).length}
          note="Across authorized services"
          icon={<ShieldCheckmarkRegular />}
        />
        <Stat
          label="Usage events"
          value={errors.usage ? '—' : usage.length}
          note="Returned by the API"
          icon={<DataTrendingRegular />}
        />
        <Stat
          label="Limit violations"
          value={errors.usage ? '—' : usage.filter(isDenial).length}
          note="Denied requests · no budget debit"
          icon={<WarningRegular />}
        />
        <Stat
          label="Estimated events"
          value={errors.usage ? '—' : usage.filter(isEstimated).length}
          note="Not equivalent to pending balance"
          icon={<ArrowClockwiseRegular />}
        />
      </section>
      <ServiceActivity usage={usage} unavailable={Boolean(errors.usage)} />
      <div className="overview-grid">
        <section className="surface">
          <div className="section-heading">
            <h2>Policy limits</h2>
            <Button appearance="subtle" size="small" onClick={() => navigate('policies')}>
              View all
            </Button>
          </div>
          {errors.policies ? (
            <p className="empty-inline">Policies are unavailable. Refresh to retry.</p>
          ) : policies.length ? (
            policies.slice(0, 5).map((policy) => (
              <div className="budget-row" key={policy.id}>
                <div>
                  <strong>{policy.name}</strong>
                  <p>
                    {services[policy.service]} · {policy.model}
                  </p>
                </div>
                <div className="budget-limit">
                  <PolicyLimit policy={policy} />
                </div>
              </div>
            ))
          ) : (
            <p className="empty-inline">No authorized policies to display.</p>
          )}
          <p className="fine-print panel-footnote">
            Configured limits, not live balances. Remaining values below are last-decision snapshots
            and may change with concurrent requests.
          </p>
        </section>
        <section className="surface">
          <div className="section-heading">
            <h2>Accounting confidence</h2>
            <Badge appearance="tint" color="brand">
              Reserve → settle
            </Badge>
          </div>
          <div className="confidence-icon">
            <ShieldCheckmarkRegular />
          </div>
          <h3>Streaming stays uninterrupted.</h3>
          <p className="muted">
            We reserve the highest applicable known input/cache rate plus maximum output before
            admission. Anthropic uses an operator-verified input ceiling. Trusted actual usage can
            release unused budget; otherwise the conservative debit stays final.
          </p>
          <div className="legend">
            <span className="legend-dot estimated" /> Estimated / conservative{' '}
            <span className="legend-dot actual" /> Actual
          </div>
          <Button appearance="subtle" onClick={() => navigate('reconciliation')}>
            Inspect reconciliation →
          </Button>
        </section>
      </div>
      <section className="surface">
        <div className="section-heading">
          <h2>Latest authorized activity</h2>
          <Button appearance="subtle" size="small" onClick={() => navigate('usage')}>
            Explore usage
          </Button>
        </div>
        <LedgerTable records={usage.slice(0, 5)} mode="usage" />
        {!usage.length && !loading && (
          <p className="empty-inline">
            {errors.usage
              ? 'Usage is unavailable. Refresh to retry.'
              : 'No authorized activity yet. Refresh after gateway requests are recorded.'}
          </p>
        )}
      </section>
    </>
  );
}
