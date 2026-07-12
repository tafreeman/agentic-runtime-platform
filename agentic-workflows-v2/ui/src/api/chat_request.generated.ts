/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/chat_request.schema.json
 * Origin Pydantic model: agentic_v2.contracts.chat.ChatRequest
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
/**
 * Request body for ``POST /api/chat``.
 *
 * ``model`` is a FULL prefixed model id (e.g.
 * ``openrouter:meta-llama/llama-3.1-8b-instruct:free``). The endpoint
 * builds exactly that model via ``langchain.models.get_chat_model``,
 * bypassing ``SmartModelRouter`` tier selection.
 */
export interface ChatRequest {
  /**
   * Conversation history, oldest first
   *
   * @minItems 1
   * @maxItems 100
   */
  messages: [ChatMessage, ...ChatMessage[]];
  /**
   * Full prefixed model id to chat with
   */
  model: string;
  /**
   * Sampling temperature
   */
  temperature?: number;
}
/**
 * One conversation turn submitted to the chat playground.
 *
 * ``content`` is capped well above any real chat turn so a single request
 * cannot buffer unbounded memory through the sanitization middleware.
 */
export interface ChatMessage {
  content: string;
  role: 'system' | 'user' | 'assistant';
}
