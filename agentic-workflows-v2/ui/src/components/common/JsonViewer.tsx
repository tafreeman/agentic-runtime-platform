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
}: Readonly<Props>) {
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
}: Readonly<{
  value: unknown;
  depth: number;
  expanded: boolean;
  maxDepth: number;
}>) {
  const [expanded, setExpanded] = useState(initialExpanded && depth < maxDepth);

  if (value === null) return <span className="text-b-text-dim">null</span>;
  if (value === undefined) return <span className="text-b-text-dim">undefined</span>;
  if (typeof value === "boolean")
    return <span className="text-b-amber">{String(value)}</span>;
  if (typeof value === "number")
    return <span className="text-b-blue">{value}</span>;
  if (typeof value === "string") {
    if (value.length > 200 && !expanded) {
      return (
        <span>
          <span className="text-b-green">"{value.slice(0, 200)}</span>
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="text-b-text-dim hover:text-b-text"
          >
            ...{value.length - 200} more"
          </button>
        </span>
      );
    }
    return <span className="text-b-green">"{value}"</span>;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-b-text-dim">[]</span>;
    return (
      <Collapsible
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        summary={`Array(${value.length})`}
        bracket={["[", "]"]}
      >
        {value.map((item, i) => (
          <div key={`${typeof item === 'object' ? JSON.stringify(item) : String(item)}-${i}`} className="pl-4">
            <JsonNode value={item} depth={depth + 1} expanded={false} maxDepth={maxDepth} />
            {i < value.length - 1 && <span className="text-b-text-faint">,</span>}
          </div>
        ))}
      </Collapsible>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0)
      return <span className="text-b-text-dim">{"{}"}</span>;
    return (
      <Collapsible
        expanded={expanded}
        onToggle={() => setExpanded(!expanded)}
        summary={`{${entries.length} keys}`}
        bracket={["{", "}"]}
      >
        {entries.map(([k, v], i) => (
          <div key={k} className="pl-4">
            <span className="text-b-purple">"{k}"</span>
            <span className="text-b-text-dim">: </span>
            <JsonNode value={v} depth={depth + 1} expanded={false} maxDepth={maxDepth} />
            {i < entries.length - 1 && <span className="text-b-text-faint">,</span>}
          </div>
        ))}
      </Collapsible>
    );
  }

  return <span className="text-b-text-dim">{String(value)}</span>;
}

function Collapsible({
  expanded,
  onToggle,
  summary,
  bracket,
  children,
}: Readonly<{
  expanded: boolean;
  onToggle: () => void;
  summary: string;
  bracket: [string, string];
  children: React.ReactNode;
}>) {
  return (
    <span>
      <button
        type="button"
        onClick={onToggle}
        aria-label={expanded ? "Collapse" : "Expand"}
        aria-expanded={expanded}
        className="inline-flex items-center text-b-text-dim hover:text-b-text"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
      </button>
      {expanded ? (
        <>
          <span className="text-b-text-dim">{bracket[0]}</span>
          <div>{children}</div>
          <span className="text-b-text-dim">{bracket[1]}</span>
        </>
      ) : (
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-left text-b-text-dim hover:text-b-text"
          onClick={onToggle}
        >
          {bracket[0]} {summary} {bracket[1]}
        </button>
      )}
    </span>
  );
}
