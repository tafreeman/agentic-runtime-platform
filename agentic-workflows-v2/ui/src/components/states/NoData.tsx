interface NoDataProps {
  /** What assistive tech hears instead of the dash. Defaults to "no data". */
  label?: string;
}

/**
 * Placeholder for a KPI or summary value that has no underlying data — no
 * runs yet, a query that is still loading or failed, NaN. Renders an em dash
 * visually and `label` for screen readers, so an absent metric never reads as
 * a real "0" / "0.0%". A genuine zero from real data should still render 0.
 */
export default function NoData({ label = "no data" }: Readonly<NoDataProps>) {
  return (
    <>
      <span aria-hidden="true">—</span>
      <span className="sr-only">{label}</span>
    </>
  );
}
