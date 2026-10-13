// ---------------------------------------------------------------------------
// Compile-time conformance: hand-written chat types ↔ generated wire types.
//
// `types.ts` keeps ergonomic, hand-written chat types (required `type`
// discriminators so `switch (event.type)` narrows; plain arrays for messages).
// The generated mirrors of `agentic_v2/contracts/chat.py` are drift-checked by
// CI but were never imported, so a contract change could pass CI while the UI
// types silently diverged. Every check below fails `tsc -b` (and therefore
// `npm run build`) on such drift. Nothing here exists at runtime.
//
// Known, intentional differences are listed explicitly so any *new* mismatch
// still fails:
//  - `requested_tier` / `tier`: the UI narrows to 1-5; the schema says number
//    (the 1-5 bound is a Pydantic validator, not expressible in the schema).
//  - `messages` / `content`: the schema emits bounded tuples; the UI uses
//    arrays, so those are compared element-wise instead.
// ---------------------------------------------------------------------------

import type * as WireRequest from "./chat_request.generated";
import type * as WireEvent from "./chat_stream_event.generated";
import type {
  ChatDoneEvent,
  ChatErrorEvent,
  ChatImagePart,
  ChatMediaEvent,
  ChatMessage,
  ChatRole,
  ChatRouteEvent,
  ChatTextPart,
  ChatTokenEvent,
  ModelChatRequest,
  TierChatRequest,
} from "./types";

type Equals<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
    ? true
    : false;
type Expect<T extends true> = T;

/**
 * Pydantic serialises defaulted fields (e.g. `type`, `alt`), so on the
 * server → UI path every schema-optional field is present: compare Required<>.
 */
type Sent<T> = Required<T>;

/** Keys whose types differ between the two shapes (never when identical). */
type MismatchedFields<A, B> = {
  [K in keyof A & keyof B]: Equals<A[K], B[K]> extends true ? never : K;
}[keyof A & keyof B];

/** Same key set, and every shared key has an identical type. */
type SameShape<A, B, Allowed extends PropertyKey = never> =
  Equals<keyof A, keyof B> extends true
    ? Equals<Exclude<MismatchedFields<A, B>, Allowed>, never>
    : false;

/** The UI value is accepted by the server-side schema. */
type Accepted<Ui, Wire> = [Ui] extends [Wire] ? true : false;

export type ChatWireConformance = [
  // Stream frames (server → UI).
  Expect<SameShape<Sent<WireEvent.ChatRouteEvent>, ChatRouteEvent, "requested_tier">>,
  Expect<SameShape<Sent<WireEvent.ChatTokenEvent>, ChatTokenEvent>>,
  Expect<SameShape<Sent<WireEvent.ChatMediaEvent>, ChatMediaEvent>>,
  Expect<SameShape<Sent<WireEvent.ChatDoneEvent>, ChatDoneEvent>>,
  Expect<SameShape<Sent<WireEvent.ChatErrorEvent>, ChatErrorEvent>>,
  Expect<
    Equals<
      Sent<WireEvent.ChatStreamEvent>["type"],
      ChatRouteEvent["type"] | ChatTokenEvent["type"] | ChatMediaEvent["type"]
        | ChatDoneEvent["type"] | ChatErrorEvent["type"]
    >
  >,

  // Request body (UI → server).
  Expect<Equals<keyof WireRequest.ChatMessage, keyof ChatMessage>>,
  Expect<Equals<WireRequest.ChatMessage["role"], ChatRole>>,
  Expect<Accepted<ChatTextPart, WireRequest.ChatTextPart>>,
  Expect<Accepted<ChatImagePart, WireRequest.ChatImagePart>>,
  Expect<Equals<keyof WireRequest.ChatTextPart, keyof ChatTextPart>>,
  Expect<Equals<keyof WireRequest.ChatImagePart, keyof ChatImagePart>>,
  Expect<Equals<keyof WireRequest.ModelChatRequest, Exclude<keyof ModelChatRequest, "tier">>>,
  Expect<Equals<keyof WireRequest.TierChatRequest, Exclude<keyof TierChatRequest, "model">>>,
  Expect<
    Accepted<
      Pick<ModelChatRequest, "model" | "temperature">,
      Pick<WireRequest.ModelChatRequest, "model" | "temperature">
    >
  >,
  Expect<
    Accepted<
      Pick<TierChatRequest, "tier" | "temperature">,
      Pick<WireRequest.TierChatRequest, "tier" | "temperature">
    >
  >,
];
