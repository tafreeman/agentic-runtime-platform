import { expect, test } from '@playwright/test';

/**
 * Chat playground surface — "chat playground" tab on /models
 * (ModelFinderPage → ChatPlayground).
 *
 * Wire contract (agentic_v2/contracts/chat.py,
 * agentic_v2/server/routes/chat.py): POST /api/chat routes DIRECTLY to the
 * picked model (no SmartModelRouter / tier selection) and always answers
 * HTTP 200 text/event-stream. Every stream terminates with exactly one
 * `done` frame or one `error` frame — model/provider failures never surface
 * as HTTP 4xx/5xx, only as an in-stream `{"type":"error", ...}` frame. This
 * suite never depends on a live provider: it runs against the
 * AGENTIC_NO_LLM=1 backend, whose PlaceholderChatModel always yields a
 * canned non-empty reply for any picked model, so the happy path is
 * deterministic and key-free.
 *
 * Test 1 drives the real backend end-to-end (probe → pick → send → stream →
 * done). Test 2 exercises the client's error-rendering path by stubbing
 * POST /api/chat via `page.route` to return a single wire-shaped
 * `ChatErrorEvent` frame — there is no key-free way to force a live
 * provider failure (401/429/connection-refused all need a real, broken
 * provider), so the stub instead verifies the UI's real SSE parsing renders
 * the exact discriminated-union error shape the backend contract defines.
 */
test.describe('chat playground', () => {
  test('streams a placeholder reply for a picked model', async ({ page }) => {
    await page.goto('/models');
    await page.getByTestId('chat-playground-tab').click();

    // The model picker only populates once the provider probe (fanned out
    // across every configured provider) resolves. A placeholder
    // "probing models…" <option> renders in the meantime, so counting
    // options is not enough — poll until a real model id is SELECTED.
    const modelPicker = page.getByTestId('chat-model-picker');
    await expect(modelPicker).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(() => modelPicker.inputValue(), {
        timeout: 30_000,
        message:
          'chat-model-picker must auto-select a model once the provider probe resolves',
      })
      .not.toBe('');
    await expect(modelPicker).toBeEnabled({ timeout: 30_000 });

    const selectedModel = await modelPicker.inputValue();
    expect(
      selectedModel,
      'chat-model-picker must have a non-empty selected model id',
    ).toBeTruthy();

    const promptText = 'ping from e2e';
    await page.getByTestId('chat-input').fill(promptText);
    await page.getByTestId('chat-send').click();

    // User + assistant rows both render (the assistant row may start empty
    // and fill in as the stream progresses — the count check alone doesn't
    // require content yet, that's asserted separately below).
    const chatMessages = page.locator('[data-testid="chat-message"]');
    await expect
      .poll(() => chatMessages.count(), {
        timeout: 30_000,
        message: 'expected at least a user row and an assistant row to render',
      })
      .toBeGreaterThanOrEqual(2);

    // The user row echoes exactly what was typed.
    const userMessage = page
      .locator('[data-testid="chat-message"][data-role="user"]')
      .first();
    await expect(userMessage).toContainText(promptText, { timeout: 30_000 });

    // The assistant row must carry non-empty text once the placeholder
    // model's canned reply finishes streaming in.
    const assistantMessage = page
      .locator('[data-testid="chat-message"][data-role="assistant"]')
      .first();
    await expect(assistantMessage).toBeVisible({ timeout: 30_000 });
    await expect(assistantMessage).toHaveText(/\S/, { timeout: 30_000 });

    // Terminal state: the stream ended with a `done` frame. Send is
    // disabled while the composer is empty (it was cleared on send), so
    // refill it — the button only re-enables once streaming has ended.
    await page.getByTestId('chat-input').fill('second turn');
    await expect(page.getByTestId('chat-send')).toBeEnabled({ timeout: 30_000 });

    // No error frame was ever surfaced on the happy path.
    await expect(page.getByTestId('chat-error')).toHaveCount(0);
  });

  test('surfaces a backend error event as chat-error', async ({ page }) => {
    // Stub POST /api/chat to return a single wire-shaped ChatErrorEvent
    // frame (agentic_v2/contracts/chat.py) instead of hitting the real
    // backend. This is deliberately not a live-backend failure — there is
    // no key-free way to force one — but it deterministically exercises the
    // client's real SSE parsing + error rendering against the exact pinned
    // wire shape.
    await page.route('**/api/chat', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: 'data: {"type":"error","message":"connection refused (e2e stub)","category":"transient"}\n\n',
      });
    });

    await page.goto('/models');
    await page.getByTestId('chat-playground-tab').click();

    const modelPicker = page.getByTestId('chat-model-picker');
    await expect(modelPicker).toBeVisible({ timeout: 30_000 });
    await expect
      .poll(() => modelPicker.inputValue(), {
        timeout: 30_000,
        message:
          'chat-model-picker must auto-select a model once the provider probe resolves',
      })
      .not.toBe('');

    await page.getByTestId('chat-input').fill('ping from e2e');
    await page.getByTestId('chat-send').click();

    const chatError = page.getByTestId('chat-error');
    await expect(chatError).toBeVisible({ timeout: 30_000 });
    await expect(chatError).toContainText('connection refused', { timeout: 30_000 });

    // The failed turn still returns the UI to a usable terminal state:
    // refill the composer (send disables while it is empty) and the button
    // re-enables because streaming has ended.
    await page.getByTestId('chat-input').fill('retry turn');
    await expect(page.getByTestId('chat-send')).toBeEnabled({ timeout: 30_000 });
  });
});
