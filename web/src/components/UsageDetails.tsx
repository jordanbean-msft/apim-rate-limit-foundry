import { text } from '../format';

const labels: Record<string, string> = {
  input_tokens: 'Input tokens (total, includes cache reads/writes)',
  output_tokens: 'Output tokens',
  cached_input_tokens: 'Cache reads (input subset; discounted rate)',
  cache_write_input_tokens_5m: 'Cache writes · 5 minutes (input subset; surcharge rate)',
  cache_write_input_tokens_1h: 'Cache writes · 1 hour (input subset; surcharge rate)',
  pages: 'Pages',
  text_records: 'Text records',
  requests: 'Requests',
};

export function UsageDetails({
  usage,
  anthropic,
}: {
  usage: Record<string, unknown>;
  anthropic: boolean;
}) {
  const keys = new Set(Object.keys(usage));
  if (anthropic && keys.size) {
    keys.add('cached_input_tokens');
    keys.add('cache_write_input_tokens_5m');
    keys.add('cache_write_input_tokens_1h');
  }
  if (!keys.size) return null;
  return (
    <div className="fine-print">
      <dl className="price-dimensions" aria-label="Normalized usage units">
        {[...keys].map((key) => (
          <div key={key} className="usage-unit">
            <dt>{labels[key] || key.replaceAll('_', ' ')}</dt>
            <dd>{text(usage[key])}</dd>
          </div>
        ))}
      </dl>
      {'input_tokens' in usage && (
        <p>
          Cache reads and writes are subsets already included in total input. Do not add them again.
        </p>
      )}
    </div>
  );
}
