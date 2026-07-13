/**
 * Model-family ranking wire contract — /api/models/rankings + autorank.
 *
 * The backend ranks model *families* (provider-stripped, size/quant-stripped
 * ids — see lib/modelFamily.ts for the shared normalization) with an LLM,
 * optionally grounded by live web search. Honesty rule: a score is only
 * meaningful next to its provenance — the ranker model (`ranked_with`),
 * whether web grounding was active (`grounded`), and when the cache was
 * produced (`updated_at`). The UI must surface all three; never render a
 * score as if it were a live fact.
 *
 * Endpoints (backend half implemented separately — keep shapes in sync):
 *   GET  /api/models/rankings -> 200 ModelRankingsResponse
 *   POST /api/models/autorank (body {model: string|null, force: boolean})
 *          -> 202 {status: "started", ranked_with}  job kicked off
 *          -> 200 ModelRankingsResponse             cache fresh (<7d), force=false
 *          -> 409 {detail}                          a ranking job is already running
 *          -> 503                                   AGENTIC_NO_LLM mode
 */

/** Lifecycle of the server-side ranking cache. */
export type RankingStatus = "empty" | "running" | "ready" | "failed";

/** One ranked model family: numeric score plus the ranker's reasoning. */
export interface RankingEntry {
  score: number;
  reasoning: string;
}

/** GET /api/models/rankings — cached family scores with full provenance. */
export interface ModelRankingsResponse {
  status: RankingStatus;
  /** Model id that produced the cache (null until a run has happened). */
  ranked_with: string | null;
  /** True when web-search grounding was active for the run. */
  grounded: boolean | null;
  /** ISO timestamp of the cache. */
  updated_at: string | null;
  /** Populated when status === "failed". */
  error: string | null;
  families: Record<string, RankingEntry>;
}

/** 202 — a ranking job was started. */
export interface AutorankStarted {
  status: "started";
  ranked_with: string;
}

/**
 * Client-side normalization of the 409 "job already in flight" response.
 * The wire body is just `{detail}` — startAutorank in client.ts converts it
 * to this typed variant so callers can fall through to polling the GET.
 */
export interface AutorankAlreadyRunning {
  status: "already-running";
  detail: string;
}

/**
 * POST /api/models/autorank result: 202 started, 409 already-running
 * (normalized), or the full 200 cache payload when force=false and the
 * cache is under 7 days old.
 */
export type AutorankResponse =
  | AutorankStarted
  | AutorankAlreadyRunning
  | ModelRankingsResponse;
