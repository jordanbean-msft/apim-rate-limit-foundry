import { ProgressBar } from '@fluentui/react-components';
import { WARNING_RATIO, budgetRatio, percentLabel } from './budgetMath';

/** Utilization bar that turns amber near the limit and red once the limit is reached. */
export function BudgetMeter({
  label,
  spentMicroUsd,
  limitMicroUsd,
}: {
  label: string;
  spentMicroUsd: number;
  limitMicroUsd: number;
}) {
  const ratio = budgetRatio(spentMicroUsd, limitMicroUsd);
  const color = ratio >= 1 ? 'error' : ratio >= WARNING_RATIO ? 'warning' : 'brand';
  return (
    <div className="budget-meter">
      <ProgressBar
        aria-label={`${label} used`}
        value={Math.min(ratio, 1)}
        max={1}
        color={color}
        thickness="large"
      />
      <span className="budget-meter-label">{percentLabel(ratio)} used</span>
    </div>
  );
}
