import { request } from "./api.js";
import { AiDrawerController } from "./ai-drawer.js";
import { ChatListController } from "./chat-list.js";
import { ComposerController } from "./composer.js";
import { MessageListController } from "./message-list.js";
import { conversationStore, mergeChatUpdates } from "./store.js";

let chatListController = null;
let messageListController = null;
let composerController = null;
let aiDrawerController = null;

function setupSidebarResizer() {
  const shell = document.querySelector(".wechat-shell");
  const handle = document.getElementById("sidebar-resizer");
  if (!shell || !handle) return;
  const min = 180;
  const max = 420;
  const saved = Number(localStorage.getItem("wechat-sidebar-width"));
  const apply = (width) => {
    const value = Math.round(Math.min(max, Math.max(min, Number(width) || 212)));
    shell.style.setProperty("--sidebar-width", `${value}px`);
    handle.setAttribute("aria-valuenow", String(value));
    localStorage.setItem("wechat-sidebar-width", String(value));
  };
  apply(saved || 212);
  let dragging = false;
  let pointerId = null;
  handle.addEventListener("pointerdown", (event) => {
    dragging = true;
    pointerId = event.pointerId;
    handle.setPointerCapture?.(pointerId);
    shell.classList.add("is-resizing");
    event.preventDefault();
  });
  handle.addEventListener("pointermove", (event) => {
    if (!dragging || event.pointerId !== pointerId) return;
    apply(event.clientX - shell.getBoundingClientRect().left - 60);
  });
  const stop = () => {
    dragging = false;
    pointerId = null;
    shell.classList.remove("is-resizing");
  };
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const current = Number.parseInt(getComputedStyle(shell).getPropertyValue("--sidebar-width"), 10) || 212;
    const next = event.key === "Home" ? min : event.key === "End" ? max : current + (event.key === "ArrowRight" ? 16 : -16);
    apply(next);
    event.preventDefault();
  });
}

async function selectChat(chatId) {
  conversationStore.update({ selectedChatId: chatId });
  const chat = conversationStore.getState().chatPages.flat().find((item) => item.id === chatId);
  document.getElementById("chat-title").textContent = chat?.name || chatId;
  composerController?.setChat(chatId);
  aiDrawerController?.setChat(chatId);
  if (chat) await messageListController.load(chat);
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function applyUpdates(payload) {
  const state = conversationStore.getState();
  if (payload.chats?.length || payload.chatOrder?.length) {
    conversationStore.update({ chatPages: mergeChatUpdates(state.chatPages, payload) });
    chatListController?.render();
  }
  const selected = conversationStore.getState().selectedChatId;
  if (selected && payload.messageIds?.[selected]?.length) {
    await messageListController?.refresh();
  }
  conversationStore.update({ updateCursor: Number(payload.cursor || state.updateCursor || 0) });
}

async function pollUpdates(root) {
  while (root.isConnected) {
    try {
      const cursor = conversationStore.getState().updateCursor;
      const payload = await request(`/api/updates?since=${encodeURIComponent(cursor)}`);
      await applyUpdates(payload);
      if (!payload.changed) await wait(100);
    } catch (error) {
      document.getElementById("composer-status").textContent = error.message || "增量更新暂时不可用";
      await wait(2000);
    }
  }
}

async function bootstrap() {
  const root = document.querySelector('[data-app="conversations"]');
  if (!root) return;
  window.lucide?.createIcons();
  chatListController = new ChatListController({
    element: document.getElementById("chat-list"),
    search: document.getElementById("chat-search"),
    store: conversationStore,
    onSelect: (chatId) => selectChat(chatId).catch(console.error),
  });
  messageListController = new MessageListController({
    element: document.getElementById("chat-thread"),
    indicator: document.getElementById("new-message-indicator"),
    store: conversationStore,
    capabilities: () => conversationStore.getState().capabilities,
  });
  composerController = new ComposerController({
    element: document.querySelector('[data-region="composer"]'),
    editor: document.getElementById("manual-text"),
    sendButton: document.getElementById("manual-send"),
    tools: document.getElementById("composer-tools"),
    fileInput: document.getElementById("media-file-input"),
    store: conversationStore,
    timeline: messageListController,
  });
  aiDrawerController = new AiDrawerController({
    drawer: document.getElementById("control-tabs"),
    openButton: document.getElementById("toggle-control"),
    closeButton: document.getElementById("close-control"),
    statusDot: document.getElementById("ai-status-dot"),
  });
  setupSidebarResizer();
  document.addEventListener("wechat:messages", (event) => {
    messageListController.append(event.detail?.chatId, event.detail?.messages || []);
  });
  try {
    const [, capabilities] = await Promise.all([chatListController.load(), request("/api/capabilities")]);
    conversationStore.update({ capabilities });
    composerController.applyCapabilities();
    composerController.updateState();
    pollUpdates(root).catch(console.error);
  } catch (error) {
    document.getElementById("composer-status").textContent = error.message || "能力读取失败";
  }
}

bootstrap();
