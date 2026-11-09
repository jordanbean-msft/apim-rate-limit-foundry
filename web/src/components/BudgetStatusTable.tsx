import { Badge } from '@fluentui/react-components';
import type { BudgetStatus, Organization, Assignment } from '../contracts';
import { microUsd } from '../format';

function subjectName(
  status: BudgetStatus,
  organizations: Organization[],
  assignments: Assignment[],
): string {
  if (status.subject_type === 'user') {
    const assignment = assignments.find((item) => item.principal_id === status.subject_id);
    return assignment?.display_label
      ? `${assignment.display_label} · ${status.subject_id}`
      : status.subject_id;
  }
  const organization = organizations.find((item) => item.id === status.subject_id);
  return organization ? `${organization.name} · ${organization.id}` : status.subject_id;
}

export function BudgetStatusTable({
  status,
  organizations = [],
  assignments = [],
  loading,
}: {
  status: BudgetStatus[];
  organizations?: Organization[];
  assignments?: Assignment[];
  loading: boolean;
}) {
  if (!status.length && !loading)
    return <p className="empty-inline">No configured monthly budgets apply to this account.</p>;
  return (
    <>
      <div className="table-scroll">
        <table>
          <caption className="visually-hidden">Monthly actual spend and remaining budgets</caption>
          <thead>
            <tr>
              <th>Budget</th>
              <th>Level / subject</th>
              <th>Model</th>
              <th>Actual month-to-date</th>
              <th>Monthly limit</th>
              <th>Remaining</th>
            </tr>
          </thead>
          <tbody>
            {status.map((item) => (
              <tr key={item.budget_id}>
                <td>
                  <strong>{item.name}</strong>
                  <div className="fine-print">{item.month} · UTC calendar month</div>
                </td>
                <td>
                  <Badge appearance="tint">{item.subject_type}</Badge>
                  <div>{subjectName(item, organizations, assignments)}</div>
                </td>
                <td>{item.model}</td>
                <td>{microUsd(item.spent_micro_usd)}</td>
                <td>{microUsd(item.limit_micro_usd)}</td>
                <td>{microUsd(item.remaining_micro_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fine-print panel-footnote">
        All matching user, team, and department budgets apply. Budgets check completed month-to-date
        actual spend before forwarding and record provider-reported actual cost afterward. This is a
        soft cap: concurrent in-flight requests can overshoot a limit; subsequent requests are
        denied. These values are actual usage totals, not a guaranteed invoice ceiling.
      </p>
    </>
  );
}
