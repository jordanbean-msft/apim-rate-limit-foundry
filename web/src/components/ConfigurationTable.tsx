import {
  Badge,
  Button,
  Table,
  TableBody,
  TableCell,
  TableCellLayout,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';
import { DeleteRegular, EditRegular } from '@fluentui/react-icons';
import type {
  Assignment,
  Budget,
  BudgetStatus,
  EditableCollection,
  EditableRecord,
  Organization,
  Price,
} from '../contracts';
import { microUsd } from '../format';
import { BudgetMeter } from './BudgetMeter';
import { MonthCaption } from './MonthCaption';
import { BudgetStatusNote } from './BudgetStatusTable';
import { levelLabels, modelLabel } from './budgetLabels';

function EnabledBadge({ enabled }: { enabled: boolean }) {
  return (
    <Badge appearance="tint" color={enabled ? 'success' : 'subtle'}>
      {enabled ? 'Enabled' : 'Disabled'}
    </Badge>
  );
}

/** Render the collection's wire shape without recalculating prices or substituting missing spend. */
function RecordCells({
  collection,
  record,
  organizations,
  budgetStatus,
}: {
  collection: EditableCollection;
  record: EditableRecord;
  organizations: Organization[];
  budgetStatus?: BudgetStatus;
}) {
  if (collection === 'budgets') {
    const budget = record as Budget;
    return (
      <>
        <TableCell>
          <TableCellLayout appearance="primary" description={`${budget.id} · ${budget.tenant_id}`}>
            {budget.name}
          </TableCellLayout>
        </TableCell>
        <TableCell>
          <TableCellLayout description={budget.subject_id}>
            {levelLabels[budget.subject_type]}
          </TableCellLayout>
        </TableCell>
        <TableCell>{modelLabel(budget.model)}</TableCell>
        <TableCell className="num">
          {!budget.enabled
            ? 'Not applicable'
            : budgetStatus
              ? microUsd(budgetStatus.spent_micro_usd)
              : 'Unavailable'}
        </TableCell>
        <TableCell className="num">{microUsd(budget.limit_micro_usd)}</TableCell>
        <TableCell className="num">
          {!budget.enabled
            ? 'Not applicable'
            : budgetStatus
              ? microUsd(budgetStatus.remaining_micro_usd)
              : 'Unavailable'}
        </TableCell>
        <TableCell className="meter-column">
          {budget.enabled && budgetStatus && (
            <BudgetMeter
              label={budget.name}
              spentMicroUsd={budgetStatus.spent_micro_usd}
              limitMicroUsd={budgetStatus.limit_micro_usd}
            />
          )}
        </TableCell>
        <TableCell>
          <EnabledBadge enabled={budget.enabled} />
        </TableCell>
      </>
    );
  }
  if (collection === 'organizations') {
    const organization = record as Organization;
    const parent = organizations.find((item) => item.id === organization.department_id);
    return (
      <>
        <TableCell>
          <TableCellLayout appearance="primary" description={organization.id}>
            {organization.name}
          </TableCellLayout>
        </TableCell>
        <TableCell>
          <TableCellLayout description={parent ? `in ${parent.name}` : undefined}>
            {organization.kind === 'team' ? 'Team' : 'Department'}
          </TableCellLayout>
        </TableCell>
        <TableCell>{organization.business_unit}</TableCell>
        <TableCell>{organization.cost_center}</TableCell>
        <TableCell>
          <EnabledBadge enabled={organization.enabled} />
        </TableCell>
      </>
    );
  }
  if (collection === 'assignments') {
    const assignment = record as Assignment;
    const team = organizations.find((item) => item.id === assignment.team_id);
    const department = organizations.find((item) => item.id === assignment.department_id);
    return (
      <>
        <TableCell>
          <TableCellLayout
            appearance="primary"
            description={`${assignment.id} · principal ${assignment.principal_id}`}
          >
            {assignment.display_label || assignment.principal_id}
          </TableCellLayout>
        </TableCell>
        <TableCell>
          <TableCellLayout
            description={`Department: ${department?.name ?? assignment.department_id}`}
          >
            {team?.name ?? assignment.team_id}
          </TableCellLayout>
        </TableCell>
        <TableCell>{assignment.tenant_id}</TableCell>
        <TableCell>
          <EnabledBadge enabled={assignment.enabled} />
        </TableCell>
      </>
    );
  }
  const price = record as Price;
  return (
    <>
      <TableCell>
        <TableCellLayout appearance="primary" description={`${price.id} · ${price.version}`}>
          {price.model}
        </TableCellLayout>
      </TableCell>
      <TableCell className="num">${price.input_per_million}</TableCell>
      <TableCell className="num">${price.cached_input_per_million}</TableCell>
      <TableCell className="num">${price.output_per_million}</TableCell>
    </>
  );
}

const headings: Record<EditableCollection, { label: string; numeric?: boolean }[]> = {
  budgets: [
    { label: 'Budget' },
    { label: 'Level / subject' },
    { label: 'Model' },
    { label: 'Month-to-date', numeric: true },
    { label: 'Monthly limit', numeric: true },
    { label: 'Remaining', numeric: true },
    { label: 'Used' },
    { label: 'Status' },
  ],
  organizations: [
    { label: 'Organization unit' },
    { label: 'Type' },
    { label: 'Business unit' },
    { label: 'Cost center' },
    { label: 'Status' },
  ],
  assignments: [{ label: 'User' }, { label: 'Team' }, { label: 'Tenant' }, { label: 'Status' }],
  prices: [
    { label: 'Model / price version' },
    { label: 'Input · $ per million', numeric: true },
    { label: 'Cached input · $ per million', numeric: true },
    { label: 'Output · $ per million', numeric: true },
  ],
};

/** Join configuration with optional live budget status and expose role-hinted mutation controls. */
export function ConfigurationTable({
  collection,
  records,
  organizations,
  admin,
  onEdit,
  onDelete,
  budgetStatus = [],
}: {
  collection: EditableCollection;
  records: EditableRecord[];
  organizations: Organization[];
  admin: boolean;
  onEdit: (record: EditableRecord) => void;
  onDelete: (id: string) => void;
  budgetStatus?: BudgetStatus[];
}) {
  return (
    <div className="table-scroll">
      {collection === 'budgets' && budgetStatus[0] && (
        <MonthCaption month={budgetStatus[0].month} />
      )}
      <Table aria-label={collection === 'prices' ? 'OpenAI price catalog' : collection}>
        <TableHeader>
          <TableRow>
            {headings[collection].map((heading) => (
              <TableHeaderCell
                key={heading.label}
                className={
                  heading.numeric ? 'num' : heading.label === 'Used' ? 'meter-column' : undefined
                }
              >
                {heading.label}
              </TableHeaderCell>
            ))}
            {admin && <TableHeaderCell>Actions</TableHeaderCell>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => (
            <TableRow key={record.id}>
              <RecordCells
                collection={collection}
                record={record}
                organizations={organizations}
                budgetStatus={budgetStatus.find((item) => item.budget_id === record.id)}
              />
              {admin && (
                <TableCell>
                  <div className="row-actions">
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<EditRegular />}
                      title="Edit"
                      onClick={() => onEdit(record)}
                      aria-label={`Edit ${record.id}`}
                    />
                    <Button
                      size="small"
                      appearance="subtle"
                      icon={<DeleteRegular />}
                      title="Delete"
                      onClick={() => onDelete(record.id)}
                      aria-label={`Delete ${record.id}`}
                    />
                  </div>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {collection === 'budgets' && <BudgetStatusNote />}
      {collection === 'prices' && (
        <p className="note">
          Rates are exact decimal USD strings per million tokens. The API pins the configured price
          version and computes cost in integer micro-USD; the portal never reprices usage.
        </p>
      )}
    </div>
  );
}
