/** Shown in place of a section whose request failed; other sections stay usable. */
export function Unavailable({ what }: { what: string }) {
  return <p className="empty-inline">{what} unavailable. Refresh to retry.</p>;
}
