const { test, expect } = require("@playwright/test");


const chats = [
  { id: "direct", name: "郭同学", kind: "direct", updatedAt: 100, lastActivityAt: "2026-09-20T08:00:00+08:00", lastMessagePreview: "你好", unreadCount: 0 },
  { id: "second", name: "第二个会话", kind: "direct", updatedAt: 90, lastActivityAt: "2026-09-20T07:00:00+08:00", lastMessagePreview: "在吗", unreadCount: 0 },
];

function verifiedMessage(chatId, text, id = "50") {
  return {
    id, localId: Number(id), chatId, type: 1, direction: "outgoing", timestamp: 1_758_350_000,
    sender: { id: "self", name: "我", avatar: "" }, display: { kind: "text", text }, media: [], status: "sent", content: text,
  };
}

async function setup(page, options = {}) {
  const calls = [];
  let recentMessages = options.initialMessages || [];
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
    sendText: true, sendImage: false, sendFile: false, sendSticker: false, playVoice: false, openMedia: false,
    ...(options.capabilities || {}),
  } }));
  await page.route("**/api/chats?*", (route) => route.fulfill({ json: { chats, nextCursor: null } }));
  await page.route("**/api/chats/*/messages?*", (route) => route.fulfill({ json: { messages: recentMessages, nextCursor: null } }));
  await page.route("**/api/chats/*/send", async (route) => {
    const body = route.request().postDataJSON();
    calls.push(body);
    const result = options.sendHandler
      ? await options.sendHandler(body, calls.length)
      : { status: "sent", message: verifiedMessage("direct", body.text), retryToken: null, retryable: false, clientRequestId: body.clientRequestId };
    if (result.recentMessages) {
      recentMessages = result.recentMessages;
      delete result.recentMessages;
    }
    await route.fulfill({ json: result });
  });
  await page.goto("/conversations");
  await page.locator('[data-chat-id="direct"]').click();
  await expect(page.getByRole("textbox", { name: "输入消息" })).toBeEnabled();
  return calls;
}

test("composer handles Enter, Shift+Enter and IME composition", async ({ page }) => {
  const calls = await setup(page);
  const editor = page.getByRole("textbox", { name: "输入消息" });
  const send = page.getByRole("button", { name: "发送(S)" });

  await editor.fill("   ");
  await expect(send).toBeDisabled();
  await editor.fill("第一行");
  await editor.press("Shift+Enter");
  await editor.type("第二行");
  await expect(editor).toHaveValue("第一行\n第二行");
  expect(calls).toHaveLength(0);

  await editor.dispatchEvent("compositionstart");
  await editor.press("Enter");
  await editor.dispatchEvent("compositionend");
  expect(calls).toHaveLength(0);
  await editor.press("Enter");
  await expect.poll(() => calls.length).toBe(1);
  await expect(editor).toHaveValue("");
  await expect(page.locator('[data-message-id="50"]')).toContainText("第一行");
});

test("composer saves drafts per chat and grows within bounds", async ({ page }) => {
  await setup(page);
  const editor = page.getByRole("textbox", { name: "输入消息" });
  await editor.fill("第一个草稿");
  await page.locator('[data-chat-id="second"]').click();
  await editor.fill("第二个草稿");
  await page.locator('[data-chat-id="direct"]').click();
  await expect(editor).toHaveValue("第一个草稿");
  expect(await page.evaluate(() => localStorage.getItem("wechat-draft:direct"))).toBe("第一个草稿");

  await editor.fill(Array.from({ length: 30 }, (_, index) => `第${index + 1}行`).join("\n"));
  const height = await page.locator('[data-region="composer"]').evaluate((element) => element.getBoundingClientRect().height);
  expect(height).toBeGreaterThanOrEqual(110);
  expect(height).toBeLessThanOrEqual(320);
});

test("composer keeps failed text and retries a pending bubble", async ({ page }) => {
  const calls = await setup(page, {
    sendHandler: async (body, count) => {
      if (count === 1) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        return { status: "failed", message: null, retryToken: "retry-1", retryable: true, clientRequestId: body.clientRequestId };
      }
      return { status: "sent", message: verifiedMessage("direct", body.text, "51"), retryToken: null, retryable: false, clientRequestId: body.clientRequestId };
    },
  });
  const editor = page.getByRole("textbox", { name: "输入消息" });
  await editor.fill("需要重试");
  await page.getByRole("button", { name: "发送(S)" }).click();
  await expect(page.locator(".message-row.is-pending")).toContainText("需要重试");
  const retry = page.getByRole("button", { name: "重试发送" });
  await expect(retry).toBeVisible();
  await expect(retry).toHaveAttribute("title", /发送失败/);
  await expect(editor).toHaveValue("需要重试");

  await retry.click();
  await expect.poll(() => calls.length).toBe(2);
  expect(calls[1].retryToken).toBe("retry-1");
  await expect(page.locator('[data-message-id="51"]')).toContainText("需要重试");
  await expect(editor).toHaveValue("");
});

test("composer rechecks an ambiguous send before enabling retry", async ({ page }) => {
  await setup(page, {
    sendHandler: async (body) => ({
      status: "unknown", message: null, retryToken: "ambiguous-1", retryable: true, clientRequestId: body.clientRequestId,
      recentMessages: [verifiedMessage("direct", body.text, "52")],
    }),
  });
  const editor = page.getByRole("textbox", { name: "输入消息" });
  await editor.fill("其实已经发出");
  await editor.press("Enter");

  await expect(page.locator('[data-message-id="52"]')).toContainText("其实已经发出");
  await expect(page.getByRole("button", { name: "重试发送" })).toHaveCount(0);
  await expect(editor).toHaveValue("");
});

test("composer exposes only toolbar capabilities that really exist", async ({ page }) => {
  await setup(page, { capabilities: { sendFile: true } });

  await expect(page.locator("#composer-tools")).toBeVisible();
  await expect(page.getByRole("button", { name: "发送文件" })).toBeVisible();
  await expect(page.getByRole("button", { name: "发送表情" })).toBeHidden();
  await expect(page.getByRole("button", { name: "发送图片" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /截图|通话|视频/ })).toHaveCount(0);
});
