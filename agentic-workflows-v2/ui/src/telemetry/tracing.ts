/**
 * OpenTelemetry web tracing initialisation for the Agentic Workflows UI.
 *
 * Initialises a WebTracerProvider that:
 * - Monkey-patches `window.fetch` via FetchInstrumentation so every `/api/`
 *   request automatically carries a W3C `traceparent` header.
 * - Exports spans to an OTLP HTTP collector (defaults to the same origin at
 *   `/v1/traces` so the proxy forwards to the backend collector).
 * - Reads `traceparent` from response headers to enable UI-side trace linking.
 *
 * Opt-in: the provider is only initialised when `VITE_OTEL_ENABLED=true`.
 * When disabled every exported symbol is still importable but all functions
 * are no-ops — no SDK objects are created and no network calls are made.
 *
 * @module telemetry/tracing
 */

/** The most recently seen traceparent header value, cached for UI display. */
let _lastTraceparent: string | null = null;

/** True when initTracing() has already been called. Prevents double-init. */
let _initialised = false;

/**
 * Initialise the OpenTelemetry web tracer provider.
 *
 * Safe to call multiple times — subsequent calls after the first are no-ops.
 * Also a no-op when `VITE_OTEL_ENABLED` is not set to `"true"`.
 *
 * Call this **before** `ReactDOM.createRoot()` so that the FetchInstrumentation
 * patch is in place before the first API request fires.
 *
 * The function returns void (not a Promise) so it is safe to call at module
 * top-level without an await.  The underlying SDK initialisation is
 * synchronous.  If the SDK is not installed the error is swallowed and a
 * console.warn is emitted.
 */
export function initTracing(): void {
  if (_initialised) {
    return;
  }

  const enabled = import.meta.env.VITE_OTEL_ENABLED;
  if (!enabled || enabled !== "true") {
    return;
  }

  _initialised = true;
  _initOtel().catch((err: unknown) => {
    // Never crash the app — just warn
    console.warn("[tracing] initTracing failed:", err);
  });
}

async function _initOtel(): Promise<void> {
  // Use dynamic import() to keep the SDK imports lazy and avoid bundling them
  // when VITE_OTEL_ENABLED is absent.
  const [otelSdkWeb, otelOtlpHttp, otelFetch, otelResources, otelSemconv, otelInstrumentation] =
    await Promise.all([
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/sdk-trace-web") as Promise<any>,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/exporter-trace-otlp-http") as Promise<any>,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/instrumentation-fetch") as Promise<any>,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/resources") as Promise<any>,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/semantic-conventions") as Promise<any>,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      import("@opentelemetry/instrumentation") as Promise<any>,
    ]);

  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { WebTracerProvider, BatchSpanProcessor } = otelSdkWeb;
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { OTLPTraceExporter } = otelOtlpHttp;
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { FetchInstrumentation } = otelFetch;
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { Resource } = otelResources;
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { ATTR_SERVICE_NAME } = otelSemconv;
  // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
  const { registerInstrumentations } = otelInstrumentation;

  const otlpEndpoint =
    (import.meta.env.VITE_OTEL_ENDPOINT as string | undefined) ?? "/v1/traces";

  const exporter = new OTLPTraceExporter({ url: otlpEndpoint });
  const processor = new BatchSpanProcessor(exporter);

  const provider = new WebTracerProvider({
    resource: new Resource({
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
      [ATTR_SERVICE_NAME]: "agentic-ui",
    }),
    spanProcessors: [processor],
  });

  // eslint-disable-next-line @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
  provider.register();

  registerInstrumentations({
    instrumentations: [
      new FetchInstrumentation({
        // Propagate traceparent on all /api/ requests
        propagateTraceHeaderCorsUrls: [/\/api\//],
        // Capture response headers so we can read traceparent back
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        applyCustomAttributesOnSpan: (_span: unknown, _request: unknown, response: any) => {
          // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access, @typescript-eslint/no-unsafe-call
          if (response && typeof response.headers?.get === "function") {
            // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-call, @typescript-eslint/no-unsafe-member-access
            const tp: string | null = response.headers.get("traceparent");
            if (tp) {
              _lastTraceparent = tp;
            }
          }
        },
      }),
    ],
  });

  console.info("[tracing] OpenTelemetry web tracing initialised (service=agentic-ui)");
}

/**
 * Return the trace ID from the most recently observed `traceparent` response
 * header, or `null` when no trace has been recorded yet.
 *
 * The trace ID is the second segment of the W3C traceparent string:
 * `00-{trace_id}-{span_id}-{flags}`.
 *
 * Useful for displaying a link to the trace viewer in error toasts.
 *
 * @example
 * const traceId = getTraceId();
 * if (traceId) {
 *   showErrorToast(`Error occurred. Trace: ${traceId}`);
 * }
 */
export function getTraceId(): string | null {
  return parseTraceparentId(_lastTraceparent);
}

/**
 * Parse a W3C traceparent header value and return just the trace ID segment.
 *
 * Returns `null` when the header is absent or malformed.
 *
 * @param traceparent - A W3C traceparent string, e.g.
 *   `"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"`.
 */
export function parseTraceparentId(
  traceparent: string | null | undefined
): string | null {
  if (!traceparent) {
    return null;
  }
  const parts = traceparent.split("-");
  // W3C format: {version}-{trace_id}-{span_id}-{flags} — exactly 4 parts
  if (parts.length !== 4) {
    return null;
  }
  const traceId = parts[1];
  // Trace ID must be 32 hex chars and non-zero
  if (!traceId || traceId.length !== 32 || /^0+$/.test(traceId)) {
    return null;
  }
  return traceId;
}

/**
 * Update the cached traceparent from a `Response` object.
 *
 * Call this inside `fetchJSON` or similar wrappers when you want to capture
 * the traceparent from non-instrumented fetch calls (e.g. during tests or
 * when the FetchInstrumentation is not active).
 *
 * @param response - A browser `Response` object.
 */
export function captureTraceparentFromResponse(response: Response): void {
  const tp = response.headers.get("traceparent");
  if (tp) {
    _lastTraceparent = tp;
  }
}

/**
 * Reset tracing state — exported for test isolation only.
 * @internal
 */
export function _resetTracingState(): void {
  _lastTraceparent = null;
  _initialised = false;
}
