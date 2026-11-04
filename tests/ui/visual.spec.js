const fs = require("node:fs");
const path = require("node:path");
const { test, expect } = require("@playwright/test");


const fixtureDir = path.join(__dirname, "fixtures");
const chats = JSON.parse(fs.readFileSync(path.join(fixtureDir, "conversations.json"), "utf8"));
const messages = JSON.parse(fs.readFileSync(path.join(fixtureDir, "messages.json"), "utf8"));

const capabilities = {
  sendText: true,
  sendImage: false,
  sendFile: true,
  sendSticker: true,
  playVoice: false,
  openMedia: true,
};

async function installFixtureRoutes(page, fixtureChats = chats, fixtureMessages = messages) {
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: capabilities }));
  await page.route("**/api/updates?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 50));
    route.fulfill({ json: { cursor: 1, changed: false, chats: [], chatOrder: [], messageIds: {}, daemonRevision: null } });
  });
  await page.route("**/api/chats/*/messages?*", (route) => {
    const url = new URL(route.request().url());
    const chatId = decodeURIComponent(url.pathname.split("/")[3]);
    route.fulfill({ json: { messages: fixtureMessages[chatId] || [], nextCursor: null } });
  });
  await page.route("**/api/chats?*", (route) => route.fulfill({ json: { chats: fixtureChats, nextCursor: null } }));
}

async function openFixture(page, viewport) {
  await page.setViewportSize(viewport);
  await installFixtureRoutes(page);
  await page.goto("/conversations?visual=1");
  await expect(page.locator(".conversation-item")).toHaveCount(chats.length);
  await page.locator('[data-chat-id="student-a"]').click();
  await expect(page.locator('[data-message-id="108"]')).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const bottomEdges = await page.evaluate(() => ({
    workspace: document.querySelector(".chat-workspace").getBoundingClientRect().toJSON(),
    composer: document.querySelector(".composer").getBoundingClientRect().toJSON(),
    sendButton: document.querySelector(".send-button").getBoundingClientRect().toJSON(),
  }));
  expect(bottomEdges.workspace.bottom).toBeLessThanOrEqual(viewport.height);
  expect(bottomEdges.composer.bottom).toBeLessThanOrEqual(viewport.height);
  expect(bottomEdges.sendButton.bottom).toBeLessThanOrEqual(viewport.height);
}

for (const viewport of [
  { width: 1280, height: 800 },
  { width: 1024, height: 720 },
  { width: 1440, height: 900 },
]) {
  test(`matches the ${viewport.width}x${viewport.height} desktop baseline`, async ({ page }) => {
    await openFixture(page, viewport);
    await expect(page).toHaveScreenshot(`${viewport.width}x${viewport.height}.png`, {
      animations: "disabled",
      caret: "hide",
      fullPage: true,
    });
  });
}

test("keeps exact desktop geometry with no overlap or horizontal scroll", async ({ page }) => {
  await openFixture(page, { width: 1280, height: 800 });
  const geometry = await page.evaluate(() => {
    const box = (selector) => {
      const rect = document.querySelector(selector).getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
    };
    return {
      rail: box(".navigation-rail"),
      sidebar: box(".conversation-sidebar"),
      workspace: box(".chat-workspace"),
      header: box(".chat-header"),
      messages: box(".message-list"),
      composer: box(".composer"),
      firstRow: box(".conversation-item"),
      horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  expect(geometry.rail.width).toBe(60);
  expect(geometry.sidebar.width).toBe(212);
  expect(geometry.header.height).toBe(68);
  expect(geometry.composer.height).toBe(170);
  expect(geometry.firstRow.height).toBe(68);
  expect(geometry.horizontalOverflow).toBe(0);
  expect(geometry.rail.right).toBe(geometry.sidebar.left);
  expect(geometry.sidebar.right).toBe(geometry.workspace.left);
  expect(geometry.header.bottom).toBe(geometry.messages.top);
  expect(geometry.messages.bottom).toBe(geometry.composer.top);
});

test("stays within local performance budgets with large metadata fixtures", async ({ page }) => {
  const largeChats = Array.from({ length: 1000 }, (_, index) => ({
    id: `chat-${index}`,
    name: `测试会话 ${String(index).padStart(4, "0")}`,
    kind: index % 5 === 0 ? "group" : "direct",
    updatedAt: 1_790_000_000 - index,
    lastActivityAt: "2026-09-20T09:00:00+08:00",
    lastMessageId: String(index),
    lastMessagePreview: `脱敏摘要 ${index}`,
    unreadCount: index % 7 === 0 ? 2 : 0,
  }));
  const messageMetadata = Array.from({ length: 5000 }, (_, index) => ({
    id: String(index),
    chatId: "chat-0",
    type: 1,
    direction: index % 2 ? "outgoing" : "incoming",
    timestamp: 1_790_000_000 + index,
    sender: { id: index % 2 ? "self" : "friend", name: index % 2 ? "我" : "同学" },
    display: { kind: "text", text: `消息 ${index}` },
    media: [],
  }));
  await page.setViewportSize({ width: 1280, height: 800 });
  await installFixtureRoutes(page, largeChats, {});
  const startedAt = Date.now();
  await page.goto("/conversations?performance=1");
  await expect(page.locator(".conversation-item")).toHaveCount(1000);
  expect(Date.now() - startedAt).toBeLessThan(1500);

  const interactionMs = await page.evaluate(async () => {
    const target = document.querySelector('[data-chat-id="chat-0"]');
    const before = performance.now();
    target.click();
    await new Promise(requestAnimationFrame);
    return performance.now() - before;
  });
  expect(interactionMs).toBeLessThan(100);

  const mergeMs = await page.evaluate(async ({ largeChats, messageMetadata }) => {
    const module = await import("/static/js/store.js");
    const before = performance.now();
    const pages = module.mergeChatUpdates([largeChats], {
      chats: [{ ...largeChats[0], unreadCount: 3, lastMessageId: "5000" }],
      chatOrder: ["chat-0", ...largeChats.slice(1).map((chat) => chat.id)],
    });
    const mergedMessages = module.mergeMessages(messageMetadata, [{ ...messageMetadata[4999], display: { kind: "text", text: "更新" } }]);
    if (pages[0][0].unreadCount !== 3 || mergedMessages.length !== 5000) throw new Error("merge result mismatch");
    return performance.now() - before;
  }, { largeChats, messageMetadata });
  expect(mergeMs).toBeLessThan(50);
});

test("short polling merges changed chats and refreshes selected messages", async ({ page }) => {
  let updateCalls = 0;
  let messageCalls = 0;
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: capabilities }));
  await page.route("**/api/chats?*", (route) => route.fulfill({ json: { chats, nextCursor: null } }));
  await page.route("**/api/chats/*/messages?*", (route) => {
    messageCalls += 1;
    const extra = messageCalls > 1 ? [{
      id: "109", chatId: "student-a", type: 1, direction: "incoming", timestamp: 1790000460,
      sender: { id: "student-a", name: "林同学", avatar: "" }, display: { kind: "text", text: "刚刚到的新消息" }, media: [],
    }] : [];
    route.fulfill({ json: { messages: [...messages["student-a"], ...extra], nextCursor: null } });
  });
  await page.route("**/api/updates?*", async (route) => {
    updateCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, 50));
    route.fulfill({ json: updateCalls === 1
      ? { cursor: 1, changed: false, chats: [], chatOrder: [], messageIds: {}, daemonRevision: null }
      : { cursor: 2, changed: true, chats: [{ ...chats[0], unreadCount: 1, lastMessageId: "109" }], chatOrder: [], messageIds: { "student-a": ["109"] }, daemonRevision: null } });
  });
  await page.goto("/conversations?updates=1");
  await page.locator('[data-chat-id="student-a"]').click();

  await expect(page.locator('[data-message-id="109"]')).toBeVisible({ timeout: 3000 });
  await expect(page.locator('[data-chat-id="student-a"] .unread-badge')).toHaveText("1");
});
