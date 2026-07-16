import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ChevronRight,
  Circle,
  Command,
  Database,
  Gauge,
  LayoutDashboard,
  List,
  Play,
  Radio,
  Search,
  Settings2,
  SlidersHorizontal,
  Workflow,
  X,
} from "lucide-react";
import "../styles/prototype-lab.css";

type Concept = "control" | "ledger" | "canvas";

const concepts: ReadonlyArray<{ id: Concept; index: string; name: string }> = [
  { id: "control", index: "01", name: "Control room" },
  { id: "ledger", index: "02", name: "Evidence ledger" },
  { id: "canvas", index: "03", name: "Flow canvas" },
];

const runs = [
  { id: "run_84f2", name: "support-triage", model: "GPT-4.1", score: 94.2, status: "live", time: "now" },
  { id: "run_84e9", name: "claims-review", model: "Claude 4", score: 88.7, status: "passed", time: "4m" },
  { id: "run_84d1", name: "research-brief", model: "o3", score: 72.1, status: "review", time: "18m" },
  { id: "run_84c8", name: "code-migration", model: "GPT-4.1", score: 91.4, status: "passed", time: "31m" },
];

function ConceptSwitcher({ concept, onChange }: Readonly<{ concept: Concept; onChange: (value: Concept) => void }>) {
  return (
    <div className="proto-switcher" aria-label="Prototype concepts">
      <div className="proto-switcher__brand">
        <span className="proto-mark">A</span>
        <span>ARP / DESIGN LAB</span>
        <span className="proto-switcher__demo">PROTOTYPE DATA</span>
      </div>
      <div className="proto-switcher__options">
        {concepts.map((item) => (
          <button
            type="button"
            key={item.id}
            className={concept === item.id ? "is-active" : ""}
            onClick={() => onChange(item.id)}
          >
            <span>{item.index}</span> {item.name}
          </button>
        ))}
      </div>
      <Link to="/" className="proto-exit" aria-label="Exit prototypes">
        <X size={15} />
      </Link>
    </div>
  );
}

function ControlRoom() {
  const [selected, setSelected] = useState(runs[0]!);
  const [paused, setPaused] = useState(false);

  return (
    <div className="control-room proto-enter">
      <aside className="control-rail">
        <div className="control-logo"><span>AR</span></div>
        <nav aria-label="Control room navigation">
          <button type="button" className="active" aria-label="Overview"><LayoutDashboard /></button>
          <button type="button" aria-label="Live runs"><Radio /></button>
          <button type="button" aria-label="Workflows"><Workflow /></button>
          <button type="button" aria-label="Datasets"><Database /></button>
          <button type="button" aria-label="Settings"><Settings2 /></button>
        </nav>
        <div className="control-rail__status"><span />04</div>
      </aside>

      <main className="control-main">
        <header className="control-header">
          <div>
            <span className="control-eyebrow">RUNTIME / OVERVIEW</span>
            <h1>Good morning, Taylor.</h1>
          </div>
          <div className="control-actions">
            <button type="button" className="control-command"><Command size={14} /> Search or command <kbd>⌘ K</kbd></button>
            <button type="button" className="control-new"><Play size={14} fill="currentColor" /> Start run</button>
          </div>
        </header>

        <section className="control-pulse" aria-label="System pulse">
          <div className="control-pulse__headline">
            <div><span className="live-dot" />System pulse</div>
            <span>Last 24 hours</span>
          </div>
          <div className="control-metrics">
            <div><span>Success rate</span><strong>92.8<small>%</small></strong><em>+3.4%</em></div>
            <div><span>Runs completed</span><strong>1,248</strong><em>+128</em></div>
            <div><span>Median latency</span><strong>4.2<small>s</small></strong><em className="down">−0.6s</em></div>
            <div><span>Cost per run</span><strong>$0.18</strong><em className="neutral">steady</em></div>
          </div>
          <div className="pulse-chart" aria-hidden="true">
            {[34, 48, 41, 55, 51, 72, 61, 74, 66, 83, 78, 94, 82, 89, 76, 92, 88, 96, 84, 91, 86, 98, 92, 100].map((height, index) => (
              <span key={`${height}-${index}`} style={{ height: `${height}%`, animationDelay: `${index * 24}ms` }} />
            ))}
          </div>
        </section>

        <section className="control-workspace">
          <div className="control-runs">
            <div className="control-section-title">
              <div><h2>Active & recent</h2><span>12 runs across 4 workflows</span></div>
              <button type="button"><SlidersHorizontal size={14} /> Filter</button>
            </div>
            <div className="control-table-head"><span>Run</span><span>Model</span><span>Quality</span><span>State</span><span /></div>
            {runs.map((run) => (
              <button type="button" className={`control-run ${selected.id === run.id ? "selected" : ""}`} key={run.id} onClick={() => setSelected(run)}>
                <span><i className={`run-icon ${run.status}`} /> <b>{run.name}</b><small>{run.id} · {run.time}</small></span>
                <span>{run.model}</span>
                <span><i className="quality-bar"><i style={{ width: `${run.score}%` }} /></i>{run.score}</span>
                <span className={`run-state ${run.status}`}>{run.status}</span>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>

          <aside className="control-inspector" key={selected.id}>
            <div className="inspector-title"><span>RUN INSPECTOR</span><button type="button">•••</button></div>
            <h2>{selected.name}</h2>
            <p>{selected.id} · started 2m 14s ago</p>
            <div className="run-progress"><span style={{ width: paused ? "68%" : "76%" }} /></div>
            <div className="progress-copy"><span>{paused ? "Paused" : "Step 4 of 5"}</span><b>{paused ? "68" : "76"}%</b></div>
            <ol className="step-list">
              <li className="done"><Check /><span><b>Load context</b><small>1.2s · 12.4k tokens</small></span></li>
              <li className="done"><Check /><span><b>Retrieve evidence</b><small>3 sources · 0.8s</small></span></li>
              <li className="done"><Check /><span><b>Plan response</b><small>1.9s · confidence .94</small></span></li>
              <li className="active"><Circle /><span><b>Synthesize answer</b><small>{paused ? "Waiting" : "Streaming output…"}</small></span></li>
              <li><Circle /><span><b>Grade result</b><small>Queued</small></span></li>
            </ol>
            <button type="button" className="pause-button" onClick={() => setPaused((value) => !value)}>{paused ? "Resume run" : "Pause run"}</button>
            <button type="button" className="view-button">Open live trace <ArrowRight size={14} /></button>
          </aside>
        </section>
      </main>
    </div>
  );
}

function EvidenceLedger() {
  const [tab, setTab] = useState<"runs" | "benchmarks">("runs");
  const [query, setQuery] = useState("");
  const filtered = runs.filter((run) => run.name.includes(query.toLowerCase()));

  return (
    <div className="ledger proto-enter">
      <header className="ledger-header">
        <div className="ledger-brand"><span>ARP</span><small>Agentic Runtime Platform</small></div>
        <nav><button className="active" type="button">Observe</button><button type="button">Build</button><button type="button">Evaluate</button></nav>
        <div><button type="button" className="ledger-search"><Search size={15} /> Search</button><button type="button" className="ledger-avatar">TF</button></div>
      </header>
      <main className="ledger-main">
        <section className="ledger-intro">
          <div><span className="ledger-kicker">EVALUATION WORKSPACE</span><h1>Evidence, before intuition.</h1><p>Inspect every run, compare model behavior, and promote only what survives the rubric.</p></div>
          <button type="button"><Play size={15} fill="currentColor" /> New evaluation</button>
        </section>

        <section className="ledger-scoreline">
          <div><span>Release readiness</span><strong>87</strong><small>/ 100</small></div>
          <div className="score-plot" aria-label="Scores over seven days">
            {[64, 71, 68, 78, 76, 82, 87].map((score, index) => <i key={score} style={{ height: `${score}%`, animationDelay: `${index * 70}ms` }}><span>{score}</span></i>)}
          </div>
          <div className="score-note"><span>↑ 8 points</span><p>Groundedness improved after the retrieval change. Safety is unchanged.</p></div>
        </section>

        <section className="ledger-explorer">
          <div className="ledger-tabs">
            <div><button type="button" className={tab === "runs" ? "active" : ""} onClick={() => setTab("runs")}>Evaluation runs <span>128</span></button><button type="button" className={tab === "benchmarks" ? "active" : ""} onClick={() => setTab("benchmarks")}>Benchmarks <span>6</span></button></div>
            <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter evidence" /></label>
          </div>
          {tab === "runs" ? (
            <div className="ledger-table">
              <div className="ledger-row head"><span>Workflow / run</span><span>Dataset</span><span>Model</span><span>Score</span><span>Verdict</span><span /></div>
              {filtered.map((run, index) => (
                <button type="button" className="ledger-row" key={run.id}>
                  <span><b>{run.name}</b><small>{run.id} · {index + 18} Jul, 10:{42 - index * 7}</small></span>
                  <span>{index % 2 ? "swe-bench verified" : "support-v3"}</span>
                  <span>{run.model}</span>
                  <span className="ledger-score">{run.score}<i><i style={{ width: `${run.score}%` }} /></i></span>
                  <span className={`ledger-verdict ${run.status}`}>{run.status === "live" ? "running" : run.status}</span>
                  <ArrowRight size={15} />
                </button>
              ))}
              {filtered.length === 0 && <div className="ledger-empty">No evidence matches “{query}”.</div>}
            </div>
          ) : (
            <div className="benchmark-list">
              {["SWE-bench Verified", "Support Resolution v3", "Tool-use Reliability", "Safety Boundary"].map((name, index) => (
                <button type="button" key={name}><span>0{index + 1}</span><b>{name}</b><small>{[500, 1240, 360, 824][index]} samples</small><em>{[91, 88, 84, 97][index]}%</em><ArrowRight /></button>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function FlowCanvas() {
  const [selectedNode, setSelectedNode] = useState("synthesize");
  const nodeInfo: Record<string, { title: string; type: string; model: string; latency: string }> = {
    input: { title: "Customer request", type: "Input", model: "—", latency: "12ms" },
    retrieve: { title: "Retrieve context", type: "Tool", model: "vector-search", latency: "840ms" },
    route: { title: "Intent router", type: "Classifier", model: "GPT-4.1 mini", latency: "420ms" },
    synthesize: { title: "Synthesize answer", type: "Agent", model: "GPT-4.1", latency: "2.8s" },
    guard: { title: "Policy guard", type: "Evaluator", model: "rules + o3", latency: "610ms" },
  };
  const current = nodeInfo[selectedNode]!;

  return (
    <div className="flow proto-enter">
      <header className="flow-header">
        <div className="flow-brand"><i>↗</i><span>ARP</span></div>
        <div className="flow-breadcrumb"><button type="button">Workflows</button><ChevronRight size={13} /><b>support-triage</b><span>draft</span></div>
        <div className="flow-actions"><button type="button"><List size={15} /> Runs</button><button type="button"><Play size={14} fill="currentColor" /> Test workflow</button></div>
      </header>
      <aside className="flow-tools">
        <button type="button" className="active" aria-label="Select tool">↖</button>
        <button type="button" aria-label="Add node">＋</button>
        <button type="button" aria-label="Add note">T</button>
        <span />
        <button type="button" aria-label="Zoom in">＋</button>
        <button type="button" aria-label="Zoom out">−</button>
        <button type="button" aria-label="Fit view">⌗</button>
      </aside>
      <main className="flow-canvas">
        <div className="flow-canvas__title"><span>WORKFLOW GRAPH</span><p>5 nodes · autosaved just now</p></div>
        <svg className="flow-lines" viewBox="0 0 1000 620" preserveAspectRatio="none" aria-hidden="true">
          <path d="M180 300 C250 300, 245 170, 330 170" />
          <path d="M180 300 C250 300, 245 420, 330 420" />
          <path d="M480 170 C560 170, 540 300, 620 300" className="active" />
          <path d="M480 420 C560 420, 540 300, 620 300" />
          <path d="M770 300 C830 300, 820 300, 875 300" />
        </svg>
        <button type="button" className={`flow-node input ${selectedNode === "input" ? "selected" : ""}`} onClick={() => setSelectedNode("input")}><i><ArrowRight /></i><span><small>INPUT</small><b>Customer request</b><em>message + metadata</em></span><u /></button>
        <button type="button" className={`flow-node retrieve ${selectedNode === "retrieve" ? "selected" : ""}`} onClick={() => setSelectedNode("retrieve")}><i><Database /></i><span><small>TOOL</small><b>Retrieve context</b><em>vector-search</em></span><u /></button>
        <button type="button" className={`flow-node route ${selectedNode === "route" ? "selected" : ""}`} onClick={() => setSelectedNode("route")}><i><Workflow /></i><span><small>ROUTER</small><b>Intent router</b><em>4 branches</em></span><u /></button>
        <button type="button" className={`flow-node synthesize ${selectedNode === "synthesize" ? "selected" : ""}`} onClick={() => setSelectedNode("synthesize")}><i><Gauge /></i><span><small>AGENT</small><b>Synthesize answer</b><em>GPT-4.1 · 2 tools</em></span><u /></button>
        <button type="button" className={`flow-node guard ${selectedNode === "guard" ? "selected" : ""}`} onClick={() => setSelectedNode("guard")}><i><Check /></i><span><small>EVALUATOR</small><b>Policy guard</b><em>threshold ≥ 0.85</em></span><u /></button>
      </main>
      <aside className="flow-inspector" key={selectedNode}>
        <div className="flow-inspector__top"><span>INSPECTOR</span><button type="button">•••</button></div>
        <div className="flow-node-icon"><Gauge /></div>
        <h2>{current.title}</h2><p>{current.type} node</p>
        <div className="flow-inspector__tabs"><button type="button" className="active">Configure</button><button type="button">Test</button><button type="button">Logs</button></div>
        <label>MODEL<button type="button">{current.model}<ChevronRight size={14} /></button></label>
        <label>SYSTEM INSTRUCTION<textarea defaultValue="Use the retrieved evidence to answer clearly. Cite every material claim and surface uncertainty." /></label>
        <div className="flow-stats"><span><small>Last latency</small><b>{current.latency}</b></span><span><small>Pass rate</small><b>94.2%</b></span></div>
        <button type="button" className="flow-run-node"><Play size={14} fill="currentColor" /> Run this node</button>
      </aside>
      <div className="flow-minimap"><i /><i /><i /><i /><i /></div>
    </div>
  );
}

export default function PrototypeLabPage() {
  const [concept, setConcept] = useState<Concept>("control");

  return (
    <div className="prototype-lab">
      <ConceptSwitcher concept={concept} onChange={setConcept} />
      <div className="prototype-stage" key={concept}>
        {concept === "control" && <ControlRoom />}
        {concept === "ledger" && <EvidenceLedger />}
        {concept === "canvas" && <FlowCanvas />}
      </div>
    </div>
  );
}
