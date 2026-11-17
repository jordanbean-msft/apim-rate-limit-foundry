import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Field,
  Input,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableCellLayout,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';
import { ArrowDownloadRegular } from '@fluentui/react-icons';
import type { ChargebackRow, PortalApi } from '../contracts';
import { microUsd } from '../format';
import { sumBy } from '../numbers';
import { chargebackInsights } from '../insights/chargebackInsights';
import type { InsightAction } from '../insights/types';
import { InsightsPanel } from './InsightsPanel';
import { StatCard } from './StatCard';
import { track } from '../telemetry';

/** Match accounting's UTC calendar month rather than the browser's local month boundary. */
function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

/** Download an authorized export via a short-lived object URL, not a persistent browser cache. */
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

interface Rollup {
  key: string;
  costMicroUsd: number;
  unknownRequests: number;
}

/** Sum known actual cost per key; unknown rows add to the unknown count, never to cost. */
function rollup(rows: ChargebackRow[], key: (row: ChargebackRow) => string): Rollup[] {
  const totals = new Map<string, Rollup>();
  for (const row of rows) {
    const entry = totals.get(key(row)) ?? { key: key(row), costMicroUsd: 0, unknownRequests: 0 };
    entry.costMicroUsd += row.cost_micro_usd ?? 0;
    entry.unknownRequests += row.unknown_requests;
    totals.set(entry.key, entry);
  }
  return [...totals.values()].sort((left, right) => right.costMicroUsd - left.costMicroUsd);
}

function RollupTable({ title, label, items }: { title: string; label: string; items: Rollup[] }) {
  return (
    <section className="surface rollup">
      <h2>{title}</h2>
      <Table aria-label={title} size="small">
        <TableHeader>
          <TableRow>
            <TableHeaderCell>{label}</TableHeaderCell>
            <TableHeaderCell className="num">Actual USD</TableHeaderCell>
            <TableHeaderCell className="num">Unknown</TableHeaderCell>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.key}>
              <TableCell>{item.key}</TableCell>
              <TableCell className="num">{microUsd(item.costMicroUsd)}</TableCell>
              <TableCell className="num">{item.unknownRequests.toLocaleString()}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}

/**
 * Read monthly aggregates from persisted history, which may lag or miss live Redis spend.
 * Nullable usage and explicit unknown counts must not be presented as zero-cost actuals.
 */
export function ChargebackReport({
  api,
  refreshKey,
  admin,
  onAction,
}: {
  api: PortalApi;
  refreshKey: string;
  admin: boolean;
  onAction: (action: InsightAction) => void;
}) {
  const [month, setMonth] = useState(currentMonth);
  const [rows, setRows] = useState<ChargebackRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    // Clear the previous month immediately and ignore late completions after selection changes.
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

  /** Re-fetch the chosen format: CSV is server-produced text, JSON is serialized for download. */
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

  const byDepartment = useMemo(() => rollup(rows, (row) => row.department_id), [rows]);
  const byTeam = useMemo(() => rollup(rows, (row) => row.team_id), [rows]);
  const totalMicroUsd = sumBy(byDepartment, (item) => item.costMicroUsd);
  const totalUnknown = sumBy(byDepartment, (item) => item.unknownRequests);
  const insights = useMemo(
    () => chargebackInsights(rows, month, new Date(), admin),
    [rows, month, admin],
  );

  return (
    <div className="page-stack">
      <div className="toolbar">
        <Field label="UTC month">
          <Input
            type="month"
            aria-label="Chargeback month"
            value={month}
            onChange={(_, data) => setMonth(data.value)}
          />
        </Field>
        <div className="toolbar-actions">
          <Button
            icon={<ArrowDownloadRegular />}
            disabled={loading || exporting}
            onClick={() => void exportReport('csv')}
          >
            Export CSV
          </Button>
          <Button
            icon={<ArrowDownloadRegular />}
            disabled={loading || exporting}
            onClick={() => void exportReport('json')}
          >
            Export JSON
          </Button>
        </div>
      </div>
      {!loading && !error && (insights.length > 0 || rows.length > 0) && (
        <InsightsPanel
          insights={insights}
          healthy="No unknown requests, estimates or unallocated rows."
          onAction={onAction}
        />
      )}
      {loading ? (
        <Spinner size="tiny" label="Loading chargeback report…" />
      ) : error ? (
        <div role="alert" className="surface empty-state">
          <p>Chargeback data is unavailable. No fixture data has been substituted.</p>
          <Button onClick={() => setRetry((value) => value + 1)}>Retry chargeback report</Button>
        </div>
      ) : !rows.length ? (
        <p className="empty-inline surface">No chargeable usage for this month.</p>
      ) : (
        <>
          <section className="stat-grid two" aria-label="Chargeback totals">
            <StatCard
              label="Actual spend"
              value={microUsd(totalMicroUsd)}
              note={`Finalized usage for ${month}`}
            />
            <StatCard
              label="Unknown-usage requests"
              value={totalUnknown.toLocaleString()}
              note="Reported separately, never counted as zero cost"
            />
          </section>
          <div className="rollup-grid">
            <RollupTable title="Spend by department" label="Department" items={byDepartment} />
            <RollupTable title="Spend by team" label="Team" items={byTeam} />
          </div>
          <section className="surface">
            <div className="section-heading">
              <h2>Detail</h2>
              <span className="secondary">
                Grouped by business unit, cost center, department, team, user, application and model
              </span>
            </div>
            <div className="table-scroll">
              <Table aria-label="Monthly chargeback report">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Business unit</TableHeaderCell>
                    <TableHeaderCell>Department / team</TableHeaderCell>
                    <TableHeaderCell>User / application</TableHeaderCell>
                    <TableHeaderCell>Model</TableHeaderCell>
                    <TableHeaderCell className="num">
                      Input · cached · output tokens
                    </TableHeaderCell>
                    <TableHeaderCell className="num">Actual USD</TableHeaderCell>
                    <TableHeaderCell className="num">Unknown requests</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row, index) => (
                    <TableRow key={`${row.business_unit}:${row.cost_center}:${row.model}:${index}`}>
                      <TableCell>
                        <TableCellLayout description={row.cost_center}>
                          {row.business_unit}
                        </TableCellLayout>
                      </TableCell>
                      <TableCell>
                        <TableCellLayout description={row.team_id}>
                          {row.department_id}
                        </TableCellLayout>
                      </TableCell>
                      <TableCell>
                        <TableCellLayout description={row.subscription_id}>
                          {row.user_ref}
                        </TableCellLayout>
                      </TableCell>
                      <TableCell>{row.model}</TableCell>
                      <TableCell className="num">
                        {row.input_tokens?.toLocaleString() ?? 'Unknown'} ·{' '}
                        {row.cached_input_tokens?.toLocaleString() ?? 'Unknown'} ·{' '}
                        {row.output_tokens?.toLocaleString() ?? 'Unknown'}
                      </TableCell>
                      <TableCell className="num">
                        {row.cost_micro_usd === null
                          ? 'Unknown — no actual usage reported'
                          : microUsd(row.cost_micro_usd)}
                        {row.cost_basis === 'estimated_upper_bound' && (
                          <div className="secondary">Estimated upper bound</div>
                        )}
                      </TableCell>
                      <TableCell className="num">{row.unknown_requests.toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
