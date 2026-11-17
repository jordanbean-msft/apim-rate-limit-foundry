import { useState } from 'react';
import {
  Badge,
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
} from '@fluentui/react-components';
import type { Insight, InsightAction, Severity } from '../insights/types';

const intents: Record<Severity, 'error' | 'warning' | 'info' | 'success'> = {
  critical: 'error',
  warning: 'warning',
  info: 'info',
  success: 'success',
};
const VISIBLE = 4;

/** Prioritized next steps for the current page; an empty list is an explicit all-clear. */
export function InsightsPanel({
  insights,
  healthy,
  onAction,
}: {
  insights: Insight[];
  /** All-clear text shown when nothing needs attention. */
  healthy: string;
  onAction: (action: InsightAction) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? insights : insights.slice(0, VISIBLE);
  const attention = insights.filter((item) => item.severity !== 'info').length;
  return (
    <section className="insights" aria-label="Recommended actions">
      <div className="section-heading">
        <h2>Recommended actions</h2>
        {attention > 0 && (
          <Badge appearance="filled" color="danger">
            {attention} need attention
          </Badge>
        )}
      </div>
      {!insights.length ? (
        <MessageBar intent="success">
          <MessageBarBody>
            <MessageBarTitle>No action needed</MessageBarTitle>
            {healthy}
          </MessageBarBody>
        </MessageBar>
      ) : (
        shown.map((insight) => (
          <MessageBar key={insight.id} intent={intents[insight.severity]} layout="multiline">
            <MessageBarBody>
              <MessageBarTitle>{insight.title}</MessageBarTitle>
              {insight.detail}
            </MessageBarBody>
            {insight.action && (
              <MessageBarActions>
                <Button size="small" onClick={() => onAction(insight.action!.target)}>
                  {insight.action.label}
                </Button>
              </MessageBarActions>
            )}
          </MessageBar>
        ))
      )}
      {insights.length > VISIBLE && (
        <Button
          appearance="transparent"
          size="small"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? 'Show fewer' : `Show ${insights.length - VISIBLE} more`}
        </Button>
      )}
    </section>
  );
}
