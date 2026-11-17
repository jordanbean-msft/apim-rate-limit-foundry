import { Badge } from '@fluentui/react-components';
import type { Assignment, BudgetStatus, Organization } from '../contracts';
import { microUsd } from '../format';
import { BudgetMeter } from './BudgetMeter';
import { levelLabels, levelOrder, modelLabel, subjectName } from './budgetLabels';

/** Department → team → user budget cards so each level's spend against its dollar limit is visible. */
export function BudgetCards({
  status,
  organizations,
  assignments,
}: {
  status: BudgetStatus[];
  organizations: Organization[];
  assignments: Assignment[];
}) {
  return (
    <div className="budget-groups">
      {levelOrder.map((level) => {
        const items = status
          .filter((item) => item.subject_type === level)
          .sort((left, right) => left.name.localeCompare(right.name));
        if (!items.length) return null;
        return (
          <section key={level} aria-label={`${levelLabels[level]} budgets`}>
            <h3 className="group-heading">{levelLabels[level]} budgets</h3>
            <div className="budget-grid">
              {items.map((item) => (
                <article className="surface budget-card" key={item.budget_id}>
                  <header>
                    <strong>{subjectName(item, organizations, assignments)}</strong>
                    <Badge appearance="outline" color="informative">
                      {modelLabel(item.model)}
                    </Badge>
                  </header>
                  <div className="budget-amount">
                    <span className="budget-spent">{microUsd(item.spent_micro_usd)}</span>
                    <span className="budget-limit">of {microUsd(item.limit_micro_usd)}</span>
                  </div>
                  <BudgetMeter
                    label={item.name}
                    spentMicroUsd={item.spent_micro_usd}
                    limitMicroUsd={item.limit_micro_usd}
                  />
                  <footer>{microUsd(item.remaining_micro_usd)} remaining</footer>
                </article>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
