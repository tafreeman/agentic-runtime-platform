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
 * Overloaded request body for ``POST /api/chat``.
 *
 * Exactly one routing constructor is accepted:
 *
 * * ``for_model`` / ``model`` builds one FULL prefixed model id directly;
 * * ``for_tier`` / ``tier`` resolves the configured tier and fallback chain.
 *
 * HTTP clients use the equivalent JSON union by sending either ``model`` or
 * ``tier``. Supplying both or neither is rejected by the two strict variants.
 */
export type ChatRequest = ModelChatRequest | TierChatRequest;

/**
 * Direct-model constructor for ``POST /api/chat``.
 */
export interface ModelChatRequest {
  /**
   * Conversation history, oldest first
   *
   * @minItems 1
   * @maxItems 100
   */
  messages: [ChatMessage, ...ChatMessage[]];
  /**
   * Full prefixed model id to chat with directly
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
  /**
   * Plain text or provider-neutral text/image content blocks
   */
  content:
    | string
    | [ChatTextPart | ChatImagePart]
    | [ChatTextPart | ChatImagePart, ChatTextPart | ChatImagePart]
    | [ChatTextPart | ChatImagePart, ChatTextPart | ChatImagePart, ChatTextPart | ChatImagePart]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ]
    | [
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart,
        ChatTextPart | ChatImagePart
      ];
  role: 'system' | 'user' | 'assistant';
}
/**
 * Text content inside a multimodal conversation turn.
 */
export interface ChatTextPart {
  text: string;
  type?: 'text';
}
/**
 * A request-local raster image sent to a vision-capable model.
 */
export interface ChatImagePart {
  detail?: 'auto' | 'low' | 'high';
  type?: 'image_url';
  url: string;
}
/**
 * Tier-routed constructor for ``POST /api/chat``.
 */
export interface TierChatRequest {
  /**
   * Conversation history, oldest first
   *
   * @minItems 1
   * @maxItems 100
   */
  messages: [ChatMessage, ...ChatMessage[]];
  /**
   * Sampling temperature
   */
  temperature?: number;
  /**
   * Capability tier to resolve through the model router (1-5)
   */
  tier: number;
}
