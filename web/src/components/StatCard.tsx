/** Headline number with a one-line explanation, shared by every summary row. */
export function StatCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string | number;
  note: string;
}) {
  return (
    <article className="surface stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <p>{note}</p>
    </article>
  );
}
