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
import type { Model, Price } from '../contracts';
import { Unavailable } from './Unavailable';

/** Show deployment-owned model routes and optional admin-only price-pin readiness diagnostics. */
export function ModelInventory({
  models,
  prices,
  modelsError,
  pricesError,
  loading,
  showPrices,
}: {
  models: Model[];
  prices: Price[];
  modelsError?: string;
  pricesError?: string;
  loading: boolean;
  showPrices: boolean;
}) {
  if (modelsError) return <Unavailable what="Model inventory" />;
  if (!models.length && !loading)
    return (
      <p className="empty-inline">No OpenAI models are registered in the gateway inventory.</p>
    );
  return (
    <section className="surface">
      <div className="table-scroll">
        <Table aria-label="Registered OpenAI models">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Model alias</TableHeaderCell>
              <TableHeaderCell>Provider deployment</TableHeaderCell>
              <TableHeaderCell>Price version</TableHeaderCell>
              <TableHeaderCell className="num">Max input tokens</TableHeaderCell>
              <TableHeaderCell className="num">Max output tokens</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => {
              // Readiness requires exactly one card for alias + pinned version, not just any rate.
              const matches = prices.filter(
                (price) => price.model === model.model && price.version === model.price_version,
              );
              const price = matches[0];
              const status = pricesError
                ? 'Price catalog unavailable'
                : loading
                  ? 'Checking price'
                  : matches.length === 0
                    ? 'Price not configured'
                    : matches.length > 1
                      ? 'Ambiguous price'
                      : 'Price configured';
              return (
                <TableRow key={model.id}>
                  <TableCell>
                    <TableCellLayout appearance="primary" description={model.api_protocol}>
                      {model.model}
                    </TableCellLayout>
                  </TableCell>
                  <TableCell>{model.deployment_name}</TableCell>
                  <TableCell>
                    <TableCellLayout
                      description={
                        showPrices && status === 'Price configured' && price
                          ? `Input $${price.input_per_million} · Cached $${price.cached_input_per_million} · Output $${price.output_per_million} / million tokens`
                          : undefined
                      }
                    >
                      {model.price_version}{' '}
                      {showPrices && (
                        <Badge
                          appearance="tint"
                          color={status === 'Price configured' ? 'success' : 'warning'}
                        >
                          {status}
                        </Badge>
                      )}
                    </TableCellLayout>
                  </TableCell>
                  <TableCell className="num">{model.max_input_tokens.toLocaleString()}</TableCell>
                  <TableCell className="num">{model.max_output_tokens.toLocaleString()}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <p className="note">
        Model routing and pinned price versions are deployment-managed; the portal does not
        configure provider deployment IDs.
      </p>
    </section>
  );
}
