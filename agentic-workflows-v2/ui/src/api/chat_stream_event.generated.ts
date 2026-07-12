/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/chat_stream_event.schema.json
 * Origin Pydantic model: agentic_v2.contracts.chat.ChatStreamEvent
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
export type ChatStreamEvent = ChatTokenEvent | ChatDoneEvent | ChatErrorEvent;

/**
 * Incremental text delta streamed from the model reply.
 */
export interface ChatTokenEvent {
  delta: string;
  type?: 'token';
}
/**
 * Terminal frame: the reply for ``model`` completed normally.
 */
export interface ChatDoneEvent {
  model: string;
  type?: 'done';
}
/**
 * Terminal frame: the stream failed.
 *
 * ``category`` is an :class:`agentic_v2.core.errors.ErrorCode` value
 * derived via ``classify_error`` (e.g. ``auth_error``, ``rate_limited``).
 * ``message`` is scrubbed of bearer tokens and API keys server-side before
 * it reaches the wire.
 */
export interface ChatErrorEvent {
  category: string;
  message: string;
  type?: 'error';
}
