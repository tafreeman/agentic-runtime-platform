import type { EvaluationCriterionDetail } from "../../api/types";

interface CriterionRowProps {
  criterion: EvaluationCriterionDetail;
}

// Design ref (evaluations 487-503): "Rubric criteria" rows are name / weight /
// thin accent progress bar / right-aligned score. The accent fill is the chart's
// one key mark and is uniform per the design — it is not threshold-colored.
export default function CriterionRow({ criterion }: Readonly<CriterionRowProps>) {
  const fraction = Math.max(0, Math.min(1, criterion.normalized_score));
  const pct = (criterion.normalized_score * 100).toFixed(1);

  return (
    <tr className="border-b border-el-divider-soft">
      <td className="px-3 py-[9px] font-mono text-xs text-el-secondary">
        {criterion.criterion}
      </td>
      <td className="px-3 py-[9px] text-right font-mono text-micro font-semibold tabular-nums text-el-ink">
        {pct}%
      </td>
      <td className="px-3 py-[9px]">
        <span className="font-mono text-micro text-el-muted">
          w {criterion.weight.toFixed(2)}
        </span>
      </td>
      <td className="px-3 py-[9px]">
        <span
          className="flex h-[5px] w-[70px] overflow-hidden rounded-sm bg-el-hover"
          role="progressbar"
          aria-valuenow={Math.round(fraction * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${pct}%`}
        >
          <span
            aria-hidden="true"
            className="h-full bg-el-accent"
            style={{ width: `${fraction * 100}%` }}
          />
        </span>
      </td>
      <td className="px-3 py-[9px]">
        {criterion.floor_violated && (
          <span className="font-mono text-micro text-el-danger">[FLOOR]</span>
        )}
      </td>
    </tr>
  );
}
