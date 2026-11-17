import {
  Badge,
  Table,
  TableBody,
  TableCell,
  TableCellLayout,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';
import type { BudgetStatus, Organization, Assignment } from '../contracts';
import { microUsd } from '../format';
import { BudgetMeter } from './BudgetMeter';
import { MonthCaption } from './MonthCaption';
import { levelLabels, modelLabel, sortByLevel, subjectName } from './budgetLabels';

/** Explain admission-time soft-cap behavior, not a reservation or guaranteed invoice ceiling. */
export function BudgetStatusNote() {
  return (
    <p className="note">
      All matching user, team and department budgets apply. Spend is checked against completed
      month-to-date actual usage before a request is forwarded, so concurrent in-flight requests can
      overshoot a limit; later requests are then denied. Totals are actual usage, not a guaranteed
      invoice ceiling.
    </p>
  );
}

/** Display live Redis-backed monthly status independently of asynchronously persisted usage. */
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
      {status[0] && <MonthCaption month={status[0].month} />}
      <div className="table-scroll">
        <Table aria-label="Monthly actual spend and remaining budgets">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Budget</TableHeaderCell>
              <TableHeaderCell>Level</TableHeaderCell>
              <TableHeaderCell>Model</TableHeaderCell>
              <TableHeaderCell className="num">Month-to-date</TableHeaderCell>
              <TableHeaderCell className="num">Monthly limit</TableHeaderCell>
              <TableHeaderCell className="num">Remaining</TableHeaderCell>
              <TableHeaderCell className="meter-column">Used</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortByLevel(status).map((item) => (
              <TableRow key={item.budget_id}>
                <TableCell>
                  <TableCellLayout appearance="primary" description={item.name}>
                    {subjectName(item, organizations, assignments)}
                  </TableCellLayout>
                </TableCell>
                <TableCell>
                  <Badge appearance="tint" color="informative">
                    {levelLabels[item.subject_type]}
                  </Badge>
                </TableCell>
                <TableCell>{modelLabel(item.model)}</TableCell>
                <TableCell className="num">{microUsd(item.spent_micro_usd)}</TableCell>
                <TableCell className="num">{microUsd(item.limit_micro_usd)}</TableCell>
                <TableCell className="num">{microUsd(item.remaining_micro_usd)}</TableCell>
                <TableCell className="meter-column">
                  <BudgetMeter
                    label={item.name}
                    spentMicroUsd={item.spent_micro_usd}
                    limitMicroUsd={item.limit_micro_usd}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <BudgetStatusNote />
    </>
  );
}
