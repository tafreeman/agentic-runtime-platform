import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";

interface Props {
  data: unknown;
  defaultExpanded?: boolean;
  maxDepth?: number;
}

export default function JsonViewer({
  data,
  defaultExpanded = false,
  maxDepth = 4,
}: Props) {
  return (
    <div className="font-mono text-xs leading-relaxed">
      <JsonNode value={data} depth={0} expanded={defaultExpanded} maxDepth={maxDepth} />
    </div>
  );
}

function JsonNode({
  value,
  depth,
  expanded: initialExpanded,
  maxDepth,
}: {
  value: unknown;
  depth: number;
  expanded: boolean;
  maxDepth: number;
}) {
  const [expanded, setExpanded] = useState(initialExpanded && depth < maxDepth);

  if (value === null) return <span className="text-gray-500">null</span>;
  if (value === undefined) return <span className="text-gray-500">undefined</span>;
  if (typeof value === "boolean")
    return <span className="text-amber-400">{String(value)}</span>;
  if (typeof value === "number")
    return <span className="text-blue-400">{value}</span>;
  if (typeof value === "string") {
    if (value.length > 200 && !expanded) {
      return (
        <span>
          <span className="text-green-400">"{value.slice(0, 200)}</span>
          <button
            onClick={() => setExpanded(true)}
            className="text-gray-500 hover:text-gray-300"
          >
            ...{value.length - 200} more"
          </button>
        </span>
      );
    }
    return <span className="text-green-400">"{value}"</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-gray-500">[]</span>;
    return (
      <Collapsible
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        summary={`Array(${value.length})`}
        bracket={["[", "]"]}
      >
        {value.map((item, i) => (
          <div key={i} className="pl-4">
            <JsonNode value={item} depth={depth + 1} expanded={false} maxDepth={maxDepth} />
            {i < value.length - 1 && <span className="text-gray-600">,</span>}
          </div>
        ))}
      </Collapsible>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0)
      return <span className="text-gray-500">{"{}"}</span>;
    return (
      <Collapsible
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        summary={`{${entries.length} keys}`}
        bracket={["{", "}"]}
      >
        {entries.map(([k, v], i) => (
          <div key={k} className="pl-4">
            <span className="text-purple-400">"{k}"</span>
            <span className="text-gray-500">: </span>
            <JsonNode value={v} depth={depth + 1} expanded={false} maxDepth={maxDepth} />
            {i < entries.length - 1 && <span className="text-gray-600">,</span>}
          </div>
        ))}
      </Collapsible>
    );
  }

  return <span className="text-gray-400">{String(value)}</span>;
}

function Collapsible({
  expanded,
  onToggle,
  summary,
  bracket,
  children,
}: {
  expanded: boolean;
  onToggle: () => void;
  summary: string;
  bracket: [string, string];
  children: React.ReactNode;
}) {
  return (
    <span>
      <button
        onClick={onToggle}
        className="inline-flex items-center text-gray-500 hover:text-gray-300"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
      </button>
      {expanded ? (
        <>
          <span className="text-gray-500">{bracket[0]}</span>
          <div>{children}</div>
          <span className="text-gray-500">{bracket[1]}</span>
        </>
      ) : (
        <span className="cursor-pointer text-gray-500 hover:text-gray-300" onClick={onToggle}>
          {bracket[0]} {summary} {bracket[1]}
        </span>
      )}
    </span>
  );
}
