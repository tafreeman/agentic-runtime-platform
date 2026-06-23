import type { EvaluationCriterionDetail } from "../../api/types";

interface CriterionRowProps {
  criterion: EvaluationCriterionDetail;
}

// Design ref (evaluations 487-503): "Rubric criteria" rows are name / weight /
// thin clay progress bar / right-aligned score. The clay fill is intentional and
// uniform per the design — it is not threshold-colored.
export default function CriterionRow({ criterion }: Readonly<CriterionRowProps>) {
  const fraction = Math.max(0, Math.min(1, criterion.normalized_score));
  const pct = (criterion.normalized_score * 100).toFixed(1);

  return (
    <tr className="border-b border-b-line-soft">
      <td className="px-3 py-[9px] font-mono text-[11.5px] text-b-text-mid">
        {criterion.criterion}
      </td>
      <td className="px-3 py-[9px] text-right font-mono text-[11px] font-semibold tabular-nums text-b-text">
        {pct}%
      </td>
      <td className="px-3 py-[9px]">
        <span className="font-mono text-[9.5px] text-b-text-dim">
          w {criterion.weight.toFixed(2)}
        </span>
      </td>
      <td className="px-3 py-[9px]">
        <span
          className="flex h-[5px] w-[70px] overflow-hidden bg-b-bg3"
          role="progressbar"
          aria-valuenow={Math.round(fraction * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${pct}%`}
          style={{ borderRadius: "3px" }}
        >
          <span
            aria-hidden="true"
            className="h-full bg-b-clay"
            style={{ width: `${fraction * 100}%` }}
          />
        </span>
      </td>
      <td className="px-3 py-[9px]">
        {criterion.floor_violated && (
          <span className="font-mono text-[10px] text-b-red">[FLOOR]</span>
        )}
      </td>
    </tr>
  );
}
