const { test, expect } = require("@playwright/test");


const chatSummaries = [
  { id: "direct", name: "郭同学", kind: "direct", updatedAt: 100, lastActivityAt: "2026-09-20T08:00:00+08:00", lastMessagePreview: "新消息", unreadCount: 0 },
  { id: "group@chatroom", name: "测试群", kind: "group", updatedAt: 90, lastActivityAt: "2026-09-20T07:00:00+08:00", lastMessagePreview: "群消息", lastSenderName: "成员甲", unreadCount: 0 },
];

const sender = { id: "friend", name: "郭同学", avatar: "" };
const self = { id: "self", name: "我", avatar: "" };
const directMessages = [
  { id: "3", chatId: "direct", type: 1, direction: "incoming", timestamp: 1_758_337_200, sender, display: { kind: "text", text: "<img src=x onerror=window.__unsafe=1>" }, media: [] },
  { id: "4", chatId: "direct", type: 1, direction: "outgoing", timestamp: 1_758_337_260, sender: self, display: { kind: "text", text: "资料 https://example.test/course" }, media: [] },
  { id: "5", chatId: "direct", type: 3, direction: "incoming", timestamp: 1_758_337_320, sender, display: { kind: "image", alt: "图片" }, media: [{ id: "5:image", kind: "image", mimeType: "image/png", width: 320, height: 180, available: true }] },
  { id: "6", chatId: "direct", type: 47, direction: "incoming", timestamp: 1_758_337_380, sender, display: { kind: "sticker", alt: "表情包" }, media: [{ id: "6:sticker", kind: "sticker", mimeType: "image/gif", available: false }] },
  { id: "7", chatId: "direct", type: 34, direction: "incoming", timestamp: 1_758_337_440, sender, display: { kind: "voice", durationMs: 3400 }, media: [{ id: "7:voice", kind: "voice", durationMs: 3400, available: true }] },
  { id: "8", chatId: "direct", type: 49, direction: "incoming", timestamp: 1_758_337_500, sender, display: { kind: "file", fileName: "课表.pdf", size: 1024 }, media: [{ id: "8:file", kind: "file", fileName: "课表.pdf", size: 1024, available: true }] },
  { id: "9", chatId: "direct", type: 49, direction: "incoming", timestamp: 1_758_337_560, sender, display: { kind: "link", title: "课程主页", description: "课程说明", url: "https://example.test/course", source: "教务系统" }, media: [] },
  { id: "10", chatId: "direct", type: 49, direction: "incoming", timestamp: 1_758_337_620, sender, display: { kind: "quote", text: "收到", quotedSender: "我", quotedText: "原消息" }, media: [] },
  { id: "11", chatId: "direct", type: 10000, direction: "incoming", timestamp: 1_758_341_400, sender, display: { kind: "system", text: "你撤回了一条消息" }, media: [] },
  { id: "12", chatId: "direct", type: 9999, direction: "incoming", timestamp: 1_758_341_460, sender, display: { kind: "unsupported", diagnosticCode: "unsupported_message_type_9999" }, media: [] },
  ...Array.from({ length: 20 }, (_, index) => ({
    id: String(20 + index), chatId: "direct", type: 1, direction: index % 2 ? "outgoing" : "incoming",
    timestamp: 1_758_341_520 + index * 60, sender: index % 2 ? self : sender,
    display: { kind: "text", text: `填充消息 ${index + 1}` }, media: [],
  })),
];

const olderMessages = [
  { id: "1", chatId: "direct", type: 1, direction: "incoming", timestamp: 1_758_330_000, sender, display: { kind: "text", text: "更早消息一" }, media: [] },
  { id: "2", chatId: "direct", type: 1, direction: "outgoing", timestamp: 1_758_330_060, sender: self, display: { kind: "text", text: "更早消息二" }, media: [] },
];

const groupMessages = [
  { id: "101", chatId: "group@chatroom", type: 1, direction: "incoming", timestamp: 1_758_337_200, sender: { id: "member-a", name: "成员甲", avatar: "" }, display: { kind: "text", text: "大家好" }, media: [] },
  { id: "102", chatId: "group@chatroom", type: 1, direction: "incoming", timestamp: 1_758_337_260, sender: { id: "member-b", name: "成员乙", avatar: "" }, display: { kind: "text", text: "欢迎" }, media: [] },
];

const tinyPng = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64");

async function mockMessageApis(page) {
  await page.route("**/api/capabilities", (route) => route.fulfill({ json: { sendText: true, sendImage: false, sendFile: false, sendSticker: false, playVoice: false, openMedia: true } }));
  await page.route("**/api/chats?*", (route) => route.fulfill({ json: { chats: chatSummaries, nextCursor: null } }));
  await page.route("**/api/chats/*/messages/*/media", (route) => {
    if (route.request().url().includes("/5/media")) return route.fulfill({ body: tinyPng, contentType: "image/png" });
    return route.fulfill({ status: 409, json: { error: { code: "media_not_downloaded", message: "媒体尚未下载", retryable: true, details: {} } } });
  });
  await page.route("**/api/chats/*/messages?*", (route) => {
    const url = new URL(route.request().url());
    const chatId = decodeURIComponent(url.pathname.split("/")[3]);
    if (chatId === "group@chatroom") return route.fulfill({ json: { messages: groupMessages, nextCursor: null } });
    if (url.searchParams.get("before")) return route.fulfill({ json: { messages: olderMessages, nextCursor: null } });
    return route.fulfill({ json: { messages: directMessages, nextCursor: "3" } });
  });
}

async function openChat(page, chatId) {
  await page.locator(`[data-chat-id="${chatId}"]`).click();
  await expect(page.locator(".message-row").first()).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  await mockMessageApis(page);
  await page.goto("/conversations");
});

test("message timeline safely renders every supported type", async ({ page }) => {
  await openChat(page, "direct");

  for (const kind of ["text", "image", "sticker", "voice", "file", "link", "quote", "system", "unsupported"]) {
    await expect(page.locator(`[data-kind="${kind}"]`).first()).toBeVisible();
  }
  await expect(page.locator('[data-message-id="3"]')).toContainText("<img src=x onerror=window.__unsafe=1>");
  expect(await page.evaluate(() => window.__unsafe)).toBeUndefined();
  await expect(page.locator('[data-message-id="4"] a')).toHaveAttribute("href", "https://example.test/course");
  await expect(page.locator('[data-message-id="4"] .link-host')).toHaveText("example.test");
  await expect(page.locator(".date-separator")).toHaveCount(2);
  await expect(page.locator('[data-message-id="5"] .media-frame')).toHaveCSS("aspect-ratio", "320 / 180");
  await expect(page.locator('[data-message-id="6"] .media-unavailable')).toBeVisible();
  await expect(page.locator('[data-message-id="7"] button')).toBeDisabled();
  await expect(page.locator('[data-message-id="8"] button')).toBeEnabled();
});

test("message timeline preserves direct and group identity", async ({ page }) => {
  await openChat(page, "direct");
  await expect(page.locator('[data-message-id="3"]')).toHaveClass(/is-incoming/);
  await expect(page.locator('[data-message-id="4"]')).toHaveClass(/is-outgoing/);
  await expect(page.locator('[data-message-id="3"] .message-bubble')).toHaveClass(/has-tail/);

  await page.locator('[data-chat-id="group@chatroom"]').click();
  await expect(page.locator('[data-message-id="101"] .sender-name')).toHaveText("成员甲");
  await expect(page.locator('[data-message-id="102"] .sender-name')).toHaveText("成员乙");
});

test("message timeline prepends history without moving the visible anchor", async ({ page }) => {
  await openChat(page, "direct");
  const thread = page.locator("#chat-thread");
  await thread.evaluate((element) => { element.scrollTop = 0; });
  const before = await page.locator('[data-message-id="3"]').evaluate((element) => element.getBoundingClientRect().top);

  await expect(page.locator('[data-message-id="1"]')).toBeAttached();
  const after = await page.locator('[data-message-id="3"]').evaluate((element) => element.getBoundingClientRect().top);

  expect(Math.abs(after - before)).toBeLessThanOrEqual(2);
  await expect(page.locator('[data-message-id="3"]')).toHaveCount(1);
});

test("message timeline counts new messages while user is away from bottom", async ({ page }) => {
  await openChat(page, "direct");
  const thread = page.locator("#chat-thread");
  await thread.evaluate((element) => { element.scrollTop = 0; });
  expect(await thread.evaluate((element) => element.scrollHeight - element.clientHeight)).toBeGreaterThan(40);
  await page.evaluate(() => document.dispatchEvent(new CustomEvent("wechat:messages", { detail: {
    chatId: "direct",
    messages: [{ id: "99", chatId: "direct", type: 1, direction: "incoming", timestamp: 1_758_350_000, sender: { id: "friend", name: "郭同学" }, display: { kind: "text", text: "刚到的新消息" }, media: [] }],
  } })));

  const indicator = page.getByRole("button", { name: "1 条新消息" });
  await expect(indicator).toBeVisible();
  await indicator.click();
  await expect(indicator).toBeHidden();
  await expect(page.locator('[data-message-id="99"]')).toBeVisible();
  expect(await thread.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThanOrEqual(2);
});
