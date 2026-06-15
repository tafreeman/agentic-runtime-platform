import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Workflow,
  Radio,
  List,
  Database,
  Trophy,
  Cpu,
} from "lucide-react";
import { useTheme, type Theme } from "../../hooks/useTheme";

const links = [
  { to: "/", icon: LayoutDashboard, label: "dashboard", end: true },
  { to: "/workflows", icon: Workflow, label: "workflows", end: false },
  { to: "/live/latest", icon: Radio, label: "live", end: false },
  { to: "/runs", icon: List, label: "runs", end: false },
  { to: "/datasets", icon: Database, label: "datasets", end: false },
  { to: "/evaluations", icon: Trophy, label: "evals", end: false },
  { to: "/models", icon: Cpu, label: "models", end: false },
];

const THEMES: Theme[] = ["dark", "paper", "bolt"];

export default function Sidebar() {
  const [theme, setTheme] = useTheme();

  return (
    <aside className="flex h-full w-48 flex-col border-r border-b-line bg-b-bg1">
      {/* Logo */}
      <div className="px-4 py-4">
        <div
          className="font-mono text-[13px] font-bold text-b-clay"
          style={{ letterSpacing: "3px" }}
        >
          PROMPTS
        </div>
        <div className="mt-0.5 font-mono text-[10px] text-b-text-dim">
          workspace · acme
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-2">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            data-testid={`nav-${link.label}`}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-sm border-l-2 px-3 py-2 font-mono text-[11px] transition-colors ${
                isActive
                  ? "border-b-clay bg-b-clay-soft text-b-clay"
                  : "border-transparent text-b-text-dim hover:bg-b-bg2 hover:text-b-text"
              } focus:outline-none focus:ring-1 focus:ring-b-clay/50`
            }
          >
            <link.icon className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{link.label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Footer: version + theme toggle */}
      <div className="border-t border-b-line px-4 py-2.5">
        <div className="mb-2 font-mono text-[10px] text-b-text-faint">
          v0.1.0
        </div>
        <div className="flex items-center gap-1.5">
          {THEMES.map((t) => {
            const active = theme === t;
            return (
              <button
                key={t}
                type="button"
                onClick={() => setTheme(t)}
                aria-pressed={active}
                className={`font-mono text-[9px] uppercase tracking-[0.5px] transition-colors focus:outline-none focus:ring-1 focus:ring-b-clay/50 ${
                  active
                    ? "text-b-clay"
                    : "text-b-text-faint hover:text-b-text-dim"
                }`}
              >
                [{t}]
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
