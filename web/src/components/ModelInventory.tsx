import { Badge } from '@fluentui/react-components';
import type { Model, Price } from '../contracts';

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
  if (modelsError)
    return <p className="empty-inline">Model inventory unavailable. Refresh to retry.</p>;
  if (!models.length && !loading)
    return (
      <p className="empty-inline">No OpenAI models are registered in the gateway inventory.</p>
    );
  return (
    <section className="surface data-panel">
      <div className="table-scroll">
        <table>
          <caption className="visually-hidden">Registered OpenAI models</caption>
          <thead>
            <tr>
              <th>Protocol / alias</th>
              <th>Provider deployment</th>
              <th>Price version / readiness</th>
              <th>Token limits</th>
            </tr>
          </thead>
          <tbody>
            {models.map((model) => {
              const matches = prices.filter(
                (price) => price.model === model.model && price.version === model.price_version,
              );
              const price = matches[0];
              const status = !showPrices
                ? 'Price pin managed by deployment'
                : pricesError
                  ? 'Price catalog unavailable'
                  : loading
                    ? 'Checking price'
                    : matches.length === 0
                      ? 'Price not configured'
                      : matches.length > 1
                        ? 'Ambiguous price'
                        : 'Price configured';
              return (
                <tr key={model.id}>
                  <td>
                    <strong>{model.model}</strong>
                    <div className="fine-print">{model.api_protocol}</div>
                  </td>
                  <td>{model.deployment_name}</td>
                  <td>
                    <div>{model.price_version}</div>
                    <Badge
                      appearance="tint"
                      color={status === 'Price configured' || !showPrices ? 'success' : 'warning'}
                    >
                      {status}
                    </Badge>
                    {showPrices && status === 'Price configured' && price && (
                      <div className="fine-print">
                        Input ${price.input_per_million} · Cached ${price.cached_input_per_million}{' '}
                        · Output ${price.output_per_million} / million tokens
                      </div>
                    )}
                  </td>
                  <td>
                    Input {model.max_input_tokens.toLocaleString()}
                    <br />
                    Output {model.max_output_tokens.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="fine-print panel-footnote">
        The gateway supports OpenAI Chat Completions and Responses. Model routing and pinned price
        versions are deployment-managed; the portal does not configure provider deployment IDs.
      </p>
    </section>
  );
}
