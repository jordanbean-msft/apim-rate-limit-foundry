import { useEffect, useState } from 'react';
import { Button, Input, Spinner } from '@fluentui/react-components';
import type { ChargebackRow, PortalApi } from '../contracts';
import { microUsd } from '../format';
import { track } from '../telemetry';

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function download(content: string, month: string, format: 'json' | 'csv'): void {
  const blob = new Blob([content], {
    type: format === 'json' ? 'application/json' : 'text/csv',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `chargeback-${month}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ChargebackReport({ api, refreshKey }: { api: PortalApi; refreshKey: string }) {
  const [month, setMonth] = useState(currentMonth);
  const [rows, setRows] = useState<ChargebackRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);
    setRows([]);
    void api
      .chargeback(month, 'json')
      .then((result) => {
        if (active && Array.isArray(result)) setRows(result);
        else if (active) setError(true);
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, month, refreshKey, retry]);

  async function exportReport(format: 'json' | 'csv') {
    setExporting(true);
    try {
      const result = await api.chargeback(month, format);
      const content = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
      download(content, month, format);
      track('portal_chargeback_export', { format, outcome: 'success' });
    } catch {
      track('portal_chargeback_export', { format, outcome: 'failure' });
      setError(true);
    } finally {
      setExporting(false);
    }
  }

  return (
    <section className="surface data-panel">
      <div className="table-toolbar">
        <label>
          UTC month
          <Input
            type="month"
            aria-label="Chargeback month"
            value={month}
            onChange={(_, data) => setMonth(data.value)}
          />
        </label>
        <Button disabled={loading || exporting} onClick={() => void exportReport('json')}>
          Export JSON
        </Button>
        <Button disabled={loading || exporting} onClick={() => void exportReport('csv')}>
          Export CSV
        </Button>
      </div>
      <p className="muted">
        Actual finalized usage grouped by business unit, cost center, department, team, user
        reference, application, model, and UTC month. Unknown stream usage is reported separately
        and is never represented as zero-cost actual usage.
      </p>
      {loading ? (
        <Spinner size="tiny" label="Loading chargeback report…" />
      ) : error ? (
        <div role="alert">
          Chargeback data is unavailable. No fixture data has been substituted.
          <Button onClick={() => setRetry((value) => value + 1)}>Retry chargeback report</Button>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">Monthly chargeback report</caption>
            <thead>
              <tr>
                <th>Business unit / cost center</th>
                <th>Department / team</th>
                <th>User reference / application</th>
                <th>Model / month</th>
                <th>Input · cached · output tokens</th>
                <th>Actual USD</th>
                <th>Unknown requests</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.business_unit}:${row.cost_center}:${row.model}:${index}`}>
                  <td>
                    {row.business_unit}
                    <div className="fine-print">{row.cost_center}</div>
                  </td>
                  <td>
                    {row.department_id}
                    <div className="fine-print">{row.team_id}</div>
                  </td>
                  <td>
                    {row.user_ref}
                    <div className="fine-print">{row.subscription_id}</div>
                  </td>
                  <td>
                    {row.model}
                    <div className="fine-print">{row.month}</div>
                  </td>
                  <td>
                    {row.input_tokens?.toLocaleString() ?? 'Unknown'} ·{' '}
                    {row.cached_input_tokens?.toLocaleString() ?? 'Unknown'} ·{' '}
                    {row.output_tokens?.toLocaleString() ?? 'Unknown'}
                  </td>
                  <td>
                    {row.cost_micro_usd === null
                      ? 'Unknown — no actual usage reported'
                      : microUsd(row.cost_micro_usd)}
                  </td>
                  <td>{row.unknown_requests.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="empty-inline">No chargeable usage for this month.</p>}
        </div>
      )}
    </section>
  );
}
