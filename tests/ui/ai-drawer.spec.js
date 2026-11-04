const { test, expect } = require("@playwright/test");


const chats = [
  { id: "direct", name: "郭同学", kind: "direct", updatedAt: 100, lastActivityAt: "2026-09-20T08:00:00+08:00", lastMessagePreview: "你好", unreadCount: 0 },
  { id: "second", name: "第二个会话", kind: "direct", updatedAt: 90, lastActivityAt: "2026-09-20T07:00:00+08:00", lastMessagePreview: "在吗", unreadCount: 0 },
];

async function setup(page) {
  const applied = [];
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: { sendText: true, sendImage: false, sendFile: false, sendSticker: false, playVoice: false, openMedia: false } }));
  await page.route("**/api/chats?*", (route) => route.fulfill({ json: { chats, nextCursor: null } }));
  await page.route("**/api/chats/*/messages?*", (route) => route.fulfill({ json: { messages: [], nextCursor: null } }));
  await page.route("**/api/chats/*/ai-control", (route) => {
    const chatId = decodeURIComponent(new URL(route.request().url()).pathname.split("/")[3]);
    route.fulfill({ json: {
      chatId,
      chatName: chatId === "direct" ? "郭同学" : "第二个会话",
      isGroup: false,
      unlocked: false,
      replyMode: chatId === "direct" ? "auto" : "manual",
      resolvedRule: { instruction: chatId === "direct" ? "活泼一点" : "简短回复", source_rule_ids: [] },
      lastAiSend: null,
      nextAllowedGroupReplyAt: null,
      modelRoute: { provider_id: "siliconflow", model: "Qwen/Qwen2.5-7B-Instruct" },
      openActions: chatId === "second" ? [{ id: "a1", kind: "send_failed", summary: "一条发送失败", status: "open" }] : [],
      health: chatId === "second" ? "action-required" : "healthy",
    } });
  });
  await page.route("**/api/commands/preview", async (route) => {
    const body = route.request().postDataJSON();
    const highRisk = body.text.includes("高风险");
    route.fulfill({ json: {
      commandId: highRisk ? "cmd-high" : "cmd-low",
      status: "draft",
      requiresConfirmation: highRisk,
      operations: [{
        op: highRisk ? "send_message" : "set_contact_rule",
        target: body.chatId,
        before: { instruction: "活泼一点" },
        after: highRisk ? { target_id: body.chatId, text: "你好" } : { target_id: body.chatId, instruction: "更简短" },
        risk: highRisk ? "high" : "low",
        summary: highRisk ? "发送消息" : "修改联系人规则",
      }],
    } });
  });
  await page.route("**/api/commands/*/apply", async (route) => {
    applied.push(route.request().postDataJSON());
    route.fulfill({ json: { commandId: "cmd", status: "applied", results: [] } });
  });
  await page.route("**/api/chats/*/send", async (route) => {
    const body = route.request().postDataJSON();
    route.fulfill({ json: {
      status: "sent", retryToken: null, retryable: false, clientRequestId: body.clientRequestId,
      message: { id: "70", chatId: "direct", type: 1, direction: "outgoing", timestamp: 1_758_350_000, sender: { id: "self", name: "我" }, display: { kind: "text", text: body.text }, media: [], status: "sent", content: body.text },
    } });
  });
  await page.goto("/conversations");
  await page.locator('[data-chat-id="direct"]').click();
  return applied;
}

test("AI drawer overlays without resizing and traps focus", async ({ page }) => {
  await setup(page);
  const drawer = page.locator('[data-region="ai-drawer"]');
  const workspace = page.locator(".chat-workspace");
  const widthBefore = await workspace.evaluate((element) => element.getBoundingClientRect().width);
  await expect(drawer).toBeHidden();

  await page.getByRole("button", { name: "打开 AI 控制" }).click();
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveCSS("width", "360px");
  expect(await workspace.evaluate((element) => element.getBoundingClientRect().width)).toBe(widthBefore);
  await expect(page.getByRole("button", { name: "关闭 AI 控制" })).toBeFocused();

  await page.keyboard.press("Shift+Tab");
  expect(await page.evaluate(() => document.activeElement.closest('[data-region="ai-drawer"]') !== null)).toBeTruthy();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("AI drawer follows chat context and keeps command drafts separate", async ({ page }) => {
  await setup(page);
  await page.getByRole("button", { name: "打开 AI 控制" }).click();
  await expect(page.locator("#ai-chat-name")).toHaveText("郭同学");
  await expect(page.locator("#ai-reply-mode")).toHaveText("自动回复");
  await expect(page.locator("#ai-unlock-state")).toHaveText("未解锁");
  await page.getByRole("textbox", { name: "自然语言要求" }).fill("第一个会话要求");

  await page.locator('[data-chat-id="second"]').click();
  await expect(page.locator("#ai-chat-name")).toHaveText("第二个会话");
  await expect(page.locator("#ai-reply-mode")).toHaveText("人工处理");
  await expect(page.locator("#ai-open-actions")).toContainText("一条发送失败");
  await expect(page.getByRole("textbox", { name: "自然语言要求" })).toHaveValue("");
  await page.getByRole("textbox", { name: "自然语言要求" }).fill("第二个会话要求");

  await page.locator('[data-chat-id="direct"]').click();
  await expect(page.getByRole("textbox", { name: "自然语言要求" })).toHaveValue("第一个会话要求");
  await expect(page.locator("body")).not.toContainText("unlock_chat");
});

test("AI drawer previews diffs and requires a high-risk confirmation", async ({ page }) => {
  const applied = await setup(page);
  await page.getByRole("button", { name: "打开 AI 控制" }).click();
  const input = page.getByRole("textbox", { name: "自然语言要求" });
  await input.fill("执行一个高风险操作");
  await page.getByRole("button", { name: "预览修改" }).click();

  await expect(page.locator("#ai-diff")).toContainText("发送消息");
  await expect(page.locator("#ai-diff")).toContainText("你好");
  const apply = page.getByRole("button", { name: "应用修改" });
  await expect(apply).toBeDisabled();
  await page.getByRole("checkbox", { name: "确认执行高风险操作" }).check();
  await expect(apply).toBeEnabled();
  await apply.click();
  await expect.poll(() => applied.length).toBe(1);
  expect(applied[0]).toEqual({ confirmHighRisk: true });
});

test("manual send never changes unlock state in the AI drawer", async ({ page }) => {
  await setup(page);
  const editor = page.getByRole("textbox", { name: "输入消息" });
  await editor.fill("本人手动回复");
  await editor.press("Enter");
  await expect(editor).toHaveValue("");

  await page.getByRole("button", { name: "打开 AI 控制" }).click();
  await expect(page.locator("#ai-unlock-state")).toHaveText("未解锁");
  await expect(page.locator("#ai-status-dot")).toHaveClass(/is-healthy/);
});
