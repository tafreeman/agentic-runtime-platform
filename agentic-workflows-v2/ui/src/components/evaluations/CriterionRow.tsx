import type { EvaluationCriterionDetail } from "../../api/types";
import BAsciiBar from "../common/BAsciiBar";

interface CriterionRowProps {
  criterion: EvaluationCriterionDetail;
}

export default function CriterionRow({ criterion }: Readonly<CriterionRowProps>) {
  const pct = (criterion.normalized_score * 100).toFixed(1);
  let color: "b-green" | "b-amber" | "b-red";
  if (criterion.normalized_score >= 0.75) {
    color = "b-green";
  } else if (criterion.normalized_score >= 0.5) {
    color = "b-amber";
  } else {
    color = "b-red";
  }

  return (
    <tr className="border-b border-b-line-soft">
      <td className="px-3 py-1.5 font-mono text-[11px] text-b-text">
        {criterion.criterion}
      </td>
      <td className="px-3 py-1.5 text-right font-mono text-[11px] tabular-nums text-b-text">
        {pct}%
      </td>
      <td className="px-3 py-1.5">
        <span className="font-mono text-[10px] text-b-text-dim">
          w:{criterion.weight.toFixed(2)}
        </span>
      </td>
      <td className="px-3 py-1.5">
        <BAsciiBar value={criterion.normalized_score} width={16} color={color} />
      </td>
      <td className="px-3 py-1.5">
        {criterion.floor_violated && (
          <span className="font-mono text-[10px] text-b-red">[FLOOR]</span>
        )}
      </td>
    </tr>
  );
}
