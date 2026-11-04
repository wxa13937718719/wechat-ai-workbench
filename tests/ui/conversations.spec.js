const { test, expect } = require("@playwright/test");


const chats = [
  { id: "normal", name: "普通同学", kind: "direct", updatedAt: 1_795_000_000, lastActivityAt: "2026-09-20T08:00:00+08:00", lastMessagePreview: "明天见", unreadCount: 0 },
  { id: "selected", name: "当前会话", kind: "direct", updatedAt: 1_795_000_100, lastActivityAt: "2026-09-20T08:01:00+08:00", lastMessagePreview: "收到", unreadCount: 2, avatar: "https://example.test/avatar.jpg" },
  { id: "pinned", name: "置顶联系人", kind: "direct", updatedAt: 1_795_000_200, lastActivityAt: "2026-09-19T08:00:00+08:00", lastMessagePreview: "置顶消息", unreadCount: 0, pinned: true },
  { id: "muted", name: "免打扰群", kind: "group", updatedAt: 1_795_000_300, lastActivityAt: "2026-09-18T08:00:00+08:00", lastMessagePreview: "群消息", lastSenderName: "成员甲", unreadCount: 8, muted: true },
  { id: "draft", name: "草稿会话", kind: "direct", updatedAt: 1_795_000_400, lastActivityAt: "2026-09-17T08:00:00+08:00", lastMessagePreview: "旧消息", draft: "没发完", unreadCount: 0 },
  { id: "group", name: "五人群", kind: "group", updatedAt: 1_795_000_500, lastActivityAt: "2026-08-20T08:00:00+08:00", lastMessagePreview: "开会啦", lastSenderName: "小郭", unreadCount: 1, avatarMembers: ["/a.jpg", "/b.jpg", "/c.jpg", "/d.jpg", "/e.jpg"] },
  { id: "missing", name: "无头像联系人", kind: "direct", updatedAt: 1_795_000_600, lastActivityAt: "2025-09-20T08:00:00+08:00", lastMessagePreview: "你好", unreadCount: 0, avatar: "/missing.jpg" },
];


async function mockApis(page) {
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: { sendText: true, sendImage: false, sendFile: false, sendSticker: false, playVoice: false, openMedia: true } }));
  await page.route("**/api/chats/*/messages*", (route) => route.fulfill({ json: { messages: [], nextCursor: null } }));
  await page.route("**/api/chats?*", (route) => {
    const url = new URL(route.request().url());
    const query = (url.searchParams.get("query") || "").toLowerCase();
    const filtered = query ? chats.filter((chat) => chat.name.toLowerCase().includes(query)) : chats;
    route.fulfill({ json: { chats: filtered, nextCursor: null } });
  });
}


test.beforeEach(async ({ page }) => {
  await mockApis(page);
  await page.goto("/conversations");
});


test("chat list preserves exact geometry and authentic states", async ({ page }) => {
  await expect(page.locator(".conversation-item")).toHaveCount(chats.length);
  await expect(page.locator(".navigation-rail")).toHaveCSS("width", "60px");
  await expect(page.locator(".conversation-sidebar")).toHaveCSS("width", "212px");
  await expect(page.locator('[data-chat-id="normal"]')).toHaveCSS("height", "68px");

  await page.locator('[data-chat-id="selected"]').click();
  await expect(page.locator('[data-chat-id="selected"]')).toHaveClass(/is-active/);
  await expect(page.locator('[data-chat-id="pinned"]')).toHaveClass(/is-pinned/);
  await expect(page.locator('[data-chat-id="muted"]')).toHaveClass(/is-muted/);
  await expect(page.locator('[data-chat-id="draft"]')).toHaveClass(/has-draft/);
  await expect(page.locator('[data-chat-id="draft"] .draft-prefix')).toHaveText("[草稿]");
  await expect(page.locator('[data-chat-id="muted"] .muted-unread')).toBeVisible();
  await expect(page.locator('[data-chat-id="muted"] .conversation-preview')).toContainText("成员甲:");
});


test("chat list renders stable group collage and missing-avatar fallback", async ({ page }) => {
  await expect(page.locator('[data-chat-id="group"] .group-avatar-grid')).toHaveClass(/grid-9/);
  await expect(page.locator('[data-chat-id="group"] .group-avatar-grid img')).toHaveCount(5);
  await expect(page.locator('[data-chat-id="missing"] .avatar-fallback')).toHaveText("无");
  await expect(page.locator('[data-chat-id="missing"] .avatar')).toHaveCSS("width", "42px");
  await expect(page.locator('[data-chat-id="missing"] .avatar')).toHaveCSS("height", "42px");
});


test("chat list debounces server search and supports keyboard navigation", async ({ page }) => {
  const search = page.getByRole("searchbox", { name: "搜索会话" });
  await search.fill("置顶");
  await expect(page.locator(".conversation-item")).toHaveCount(1);
  await search.fill("不存在");
  await expect(page.locator(".list-status")).toHaveText("没有找到相关会话");
  await search.fill("");
  await expect(page.locator(".conversation-item")).toHaveCount(chats.length);

  await search.press("ArrowDown");
  await search.press("ArrowDown");
  await search.press("Enter");
  await expect(page.locator('[data-chat-id="selected"]')).toHaveClass(/is-active/);
  await search.press("Escape");
  await expect(search).toHaveValue("");
});


test("chat list reports API failure without collapsing the shell", async ({ page }) => {
  await page.route("**/api/chats?*", (route) => route.fulfill({ status: 503, json: { error: { code: "wechat_database_unavailable", message: "微信数据库暂时不可用", retryable: true, details: {} } } }));
  await page.reload();

  await expect(page.locator(".list-status")).toContainText("微信数据库暂时不可用");
  await expect(page.locator(".conversation-sidebar")).toHaveCSS("width", "212px");
});
