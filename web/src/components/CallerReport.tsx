import { useEffect, useState } from 'react';
import { Button, Input, Select, Spinner } from '@fluentui/react-components';
import type { ApplicationSubscription, CallerUsage, Policy, PortalApi } from '../contracts';
import { microUsd, services, utcTime } from '../format';
import { protocolLabel } from '../protocols';

export function CallerReport({
  api,
  refreshKey,
  policies = [],
  subscriptions = [],
}: {
  api: PortalApi;
  refreshKey: string;
  policies?: Policy[];
  subscriptions?: ApplicationSubscription[];
}) {
  const [period, setPeriod] = useState<'hour' | 'day'>('day');
  const [rows, setRows] = useState<CallerUsage[]>([]);
  const [search, setSearch] = useState('');
  const [service, setService] = useState('all');
  const [subscription, setSubscription] = useState('all');
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setRows([]);
    setError(false);
    void api
      .callers(period)
      .then(
        (result) => {
          if (active) setRows(result);
        },
        () => {
          if (active) setError(true);
        },
      )
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, period, refreshKey, retry]);

  const filtered = rows.filter(
    (row) =>
      (service === 'all' || row.service === service) &&
      (subscription === 'all' || row.subscription_id === subscription) &&
      [
        row.tenant_id,
        row.subscription_id,
        row.caller_ref,
        row.display_label,
        row.model,
        ...Object.keys(row.denied_policy_counts),
      ]
        .join(' ')
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <section className="surface data-panel">
      <p>
        One effective charge per admitted request; trusted actual usage replaces its reservation.
        Conservative spend includes unresolved requests and uncertain cache usage, not extra
        charges. UTC buckets use admission time. These are ledger estimates, not invoices.
      </p>
      <p className="fine-print">
        Match caller_ref in the Azure dashboard to an application subscription below. References are
        pseudonymous, not anonymous. Labels are administrator-configured and not directory names.
      </p>
      <div className="table-toolbar">
        <Input
          aria-label="Search application subscription report"
          placeholder="Application subscription, dashboard reference, model or policy…"
          value={search}
          onChange={(_, value) => setSearch(value.value)}
        />
        <Select
          aria-label="Application subscription"
          value={subscription}
          onChange={(_, value) => setSubscription(value.value)}
        >
          <option value="all">All application subscriptions</option>
          {subscriptions.map((item) => (
            <option key={item.id} value={item.id}>
              {item.display_name} · {item.id}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Application service"
          value={service}
          onChange={(_, value) => setService(value.value)}
        >
          <option value="all">All services</option>
          {Object.entries(services).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Reporting UTC period"
          value={period}
          onChange={(_, value) => setPeriod(value.value as 'hour' | 'day')}
        >
          <option value="day">UTC day</option>
          <option value="hour">UTC hour</option>
        </Select>
      </div>
      {loading ? (
        <Spinner size="tiny" label="Loading application subscription report…" />
      ) : error ? (
        <div role="alert">
          Application subscription report unavailable. No sample data has been substituted.
          <Button onClick={() => setRetry((value) => value + 1)}>
            Retry application subscription report
          </Button>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">
              Application subscription spend and denials
            </caption>
            <thead>
              <tr>
                <th>Application subscription / dashboard reference</th>
                <th>Service / model / UTC bucket</th>
                <th>Allowed / denied requests</th>
                <th>Effective spend (USD)</th>
                <th>Denied policies</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id}>
                  <td>
                    <strong>
                      {row.display_label ||
                        subscriptions.find((item) => item.id === row.subscription_id)
                          ?.display_name ||
                        'Application subscription'}
                    </strong>
                    <div>Subscription ID: {row.subscription_id}</div>
                    <div>Tenant: {row.tenant_id}</div>
                    <div className="fine-print">
                      caller_ref: <code>{row.caller_ref}</code>
                    </div>
                  </td>
                  <td>
                    {services[row.service]} · {row.model}
                    <div>
                      {row.service === 'foundry' && (
                        <>
                          {protocolLabel({ service: row.service, api_protocol: row.api_protocol })}{' '}
                          ·{' '}
                        </>
                      )}
                      {row.streaming ? 'Streaming' : 'Non-streaming'}
                    </div>
                    <div className="fine-print">
                      {utcTime(row.start_at)} — {utcTime(row.end_at)}
                    </div>
                  </td>
                  <td>
                    Allowed: {row.admitted_requests} · Denied: {row.denied_requests}
                    <div className="fine-print">
                      Estimated liabilities: {row.estimated_requests} requests
                    </div>
                  </td>
                  <td>
                    Total: {microUsd(row.cost_micro_usd)}
                    <div>Actual: {microUsd(row.actual_cost_micro_usd)}</div>
                    <div>Conservative: {microUsd(row.conservative_cost_micro_usd)}</div>
                    <div className="fine-print">
                      Actual + conservative = total; denials cost zero.
                    </div>
                  </td>
                  <td>
                    {Object.entries(row.denied_policy_counts).map(([id, count]) => {
                      const policy = policies.find((item) => item.id === id);
                      return (
                        <div key={id}>
                          {id}: {count}
                          {policy && (
                            <div className="fine-print">
                              Configured limit:{' '}
                              {policy.metric === 'cost'
                                ? microUsd(policy.limit)
                                : `${policy.limit.toLocaleString()} ${policy.metric.replace('_', ' ')}`}{' '}
                              / {policy.period}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {!Object.keys(row.denied_policy_counts).length && 'None'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filtered.length && <p>No matching application subscription activity.</p>}
        </div>
      )}
    </section>
  );
}
