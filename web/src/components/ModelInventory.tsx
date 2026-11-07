import { Badge } from '@fluentui/react-components';
import type { Model, Price } from '../contracts';

export function ModelInventory({
  models,
  prices,
  modelsError,
  pricesError,
  loading,
}: {
  models: Model[];
  prices: Price[];
  modelsError?: string;
  pricesError?: string;
  loading: boolean;
}) {
  if (modelsError)
    return <p className="empty-inline">Model inventory unavailable. Refresh to retry.</p>;
  if (!models.length && !loading)
    return (
      <p className="empty-inline">
        No models registered. Routing is configured through deployment.
      </p>
    );
  return (
    <section className="surface data-panel">
      <div className="table-scroll">
        <table>
          <caption className="visually-hidden">Registered models</caption>
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
                (price) =>
                  price.service === 'foundry' &&
                  price.model === model.model &&
                  price.version === model.price_version,
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
                      : model.api_protocol === 'anthropic-messages' &&
                          (price.cache_write_5m_per_million == null ||
                            price.cache_write_1h_per_million == null)
                        ? 'Cache-write rates missing'
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
                      color={status === 'Price configured' ? 'success' : 'warning'}
                    >
                      {status}
                    </Badge>
                    {status === 'Price configured' && (
                      <div className="fine-print">
                        Input ${price.input_per_million} · Output ${price.output_per_million} ·
                        Cached ${price.cached_input_per_million} / million
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
        OpenAI and Anthropic identify API protocols, not the backend account kind. Microsoft Foundry
        supports approved deployments through these protocols.
      </p>
      <p className="fine-print panel-footnote">
        Registry routing and price pins are deployment-managed. Unknown prices are not free;
        configuration alone does not guarantee request admission.
      </p>
    </section>
  );
}
