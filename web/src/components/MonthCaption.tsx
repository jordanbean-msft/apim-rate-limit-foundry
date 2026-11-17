/** Names the UTC month a budget table's spend figures belong to, once per table. */
export function MonthCaption({ month }: { month: string }) {
  return <p className="table-caption">{month} · UTC calendar month, actual spend</p>;
}
