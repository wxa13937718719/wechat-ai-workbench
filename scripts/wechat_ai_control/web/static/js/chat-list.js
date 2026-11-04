import { request } from "./api.js";


function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

function initial(name) {
  return Array.from(String(name || "?").trim())[0] || "?";
}

function formatWechatTime(value, now = new Date()) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.valueOf())) return "";
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((startToday - startDate) / 86_400_000);
  if (days === 0) return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (days === 1) return "昨天";
  if (date.getFullYear() === now.getFullYear()) return `${date.getMonth() + 1}月${date.getDate()}日`;
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}`;
}

function avatarHtml(chat) {
  const fallback = `<span class="avatar-fallback">${escapeHtml(initial(chat.name))}</span>`;
  if (chat.avatar) {
    return `<span class="avatar"><img src="${escapeHtml(chat.avatar)}" alt="">${fallback}</span>`;
  }
  const members = Array.isArray(chat.avatarMembers) ? chat.avatarMembers.slice(0, 9) : [];
  if (chat.kind === "group" && members.length) {
    const grid = members.length > 4 ? "grid-9" : "grid-4";
    const cells = members.map((avatar, index) => avatar
      ? `<img src="${escapeHtml(avatar)}" alt="">`
      : `<span class="group-avatar-cell">${index + 1}</span>`).join("");
    return `<span class="avatar"><span class="group-avatar-grid ${grid}">${cells}</span></span>`;
  }
  return `<span class="avatar">${fallback}</span>`;
}

function previewHtml(chat) {
  if (chat.draft) {
    return `<span class="draft-prefix">[草稿]</span> ${escapeHtml(chat.draft)}`;
  }
  const sender = chat.kind === "group" && chat.lastSenderName ? `${chat.lastSenderName}: ` : "";
  return `${escapeHtml(sender)}${escapeHtml(chat.lastMessagePreview || "")}`;
}

function rowClasses(chat, selected, keyboardId) {
  return [
    "conversation-item",
    chat.id === selected ? "is-active" : "",
    chat.id === keyboardId ? "is-keyboard-active" : "",
    chat.pinned ? "is-pinned" : "",
    chat.muted ? "is-muted" : "",
    chat.draft ? "has-draft" : "",
  ].filter(Boolean).join(" ");
}

export class ChatListController {
  constructor({ element, search, store, onSelect, debounceMs = 150 }) {
    this.element = element;
    this.searchInput = search;
    this.store = store;
    this.onSelect = onSelect;
    this.debounceMs = debounceMs;
    this.query = "";
    this.nextCursor = null;
    this.keyboardIndex = -1;
    this.timer = null;
    this.requestVersion = 0;
    this.bind();
  }

  bind() {
    this.element.addEventListener("click", (event) => {
      const item = event.target.closest("[data-chat-id]");
      if (item) this.select(item.dataset.chatId);
    });
    this.element.addEventListener("scroll", () => {
      const positions = { ...this.store.getState().scrollPositions, chatList: this.element.scrollTop };
      this.store.update({ scrollPositions: positions });
      if (this.nextCursor && this.element.scrollTop + this.element.clientHeight >= this.element.scrollHeight - 80) {
        this.loadMore().catch(() => {});
      }
    });
    this.searchInput.addEventListener("input", () => {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.search(this.searchInput.value), this.debounceMs);
    });
    this.searchInput.addEventListener("keydown", (event) => this.onKeyDown(event));
  }

  async load() {
    await this.fetchPage("", null, false);
  }

  async search(query) {
    this.query = String(query || "").trim();
    this.keyboardIndex = -1;
    await this.fetchPage(this.query, null, false);
  }

  async loadMore() {
    if (!this.nextCursor) return;
    await this.fetchPage(this.query, this.nextCursor, true);
  }

  async fetchPage(query, cursor, append) {
    const version = ++this.requestVersion;
    const params = new URLSearchParams({ limit: "100" });
    if (query) params.set("query", query);
    if (cursor) params.set("cursor", cursor);
    try {
      const payload = await request(`/api/chats?${params}`);
      if (version !== this.requestVersion) return;
      const oldPages = append ? this.store.getState().chatPages : [];
      const pages = [...oldPages, payload.chats || []];
      this.nextCursor = payload.nextCursor || null;
      this.store.update({ chatPages: pages });
      this.render(query ? "没有找到相关会话" : "没有会话");
    } catch (error) {
      if (version !== this.requestVersion) return;
      this.element.setAttribute("aria-busy", "false");
      this.element.innerHTML = `<div class="list-status">${escapeHtml(error.message || "会话加载失败")}</div>`;
    }
  }

  select(chatId) {
    const previous = this.store.getState().selectedChatId;
    this.store.update({ selectedChatId: chatId });
    if (previous !== chatId) {
      const oldItem = previous ? this.element.querySelector(`[data-chat-id="${CSS.escape(previous)}"]`) : null;
      const newItem = this.element.querySelector(`[data-chat-id="${CSS.escape(chatId)}"]`);
      oldItem?.classList.remove("is-active");
      oldItem?.setAttribute("aria-selected", "false");
      newItem?.classList.add("is-active");
      newItem?.setAttribute("aria-selected", "true");
    }
    this.onSelect?.(chatId);
  }

  onKeyDown(event) {
    const chats = this.store.getState().chatPages.flat();
    if (event.key === "Escape") {
      event.preventDefault();
      this.searchInput.value = "";
      this.search("");
      return;
    }
    if (!chats.length || !["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "ArrowDown") this.keyboardIndex = Math.min(chats.length - 1, this.keyboardIndex + 1);
    if (event.key === "ArrowUp") this.keyboardIndex = Math.max(0, this.keyboardIndex < 0 ? 0 : this.keyboardIndex - 1);
    if (event.key === "Enter" && this.keyboardIndex >= 0) {
      this.select(chats[this.keyboardIndex].id);
      return;
    }
    this.render(this.query ? "没有找到相关会话" : "没有会话");
    const focused = this.element.querySelector(".is-keyboard-active");
    focused?.scrollIntoView({ block: "nearest" });
  }

  render(emptyText = "没有会话") {
    const state = this.store.getState();
    const chats = state.chatPages.flat();
    const keyboardId = this.keyboardIndex >= 0 ? chats[this.keyboardIndex]?.id : null;
    this.element.setAttribute("aria-busy", "false");
    this.element.innerHTML = chats.map((chat) => `
      <button class="${rowClasses(chat, state.selectedChatId, keyboardId)}" type="button" role="option"
        aria-selected="${chat.id === state.selectedChatId}" data-chat-id="${escapeHtml(chat.id)}">
        ${avatarHtml(chat)}
        <span class="conversation-copy">
          <span class="conversation-name">${escapeHtml(chat.name)}</span>
          <span class="conversation-preview">${previewHtml(chat)}</span>
        </span>
        <span class="conversation-side">
          <span class="conversation-time">${escapeHtml(formatWechatTime(chat.lastActivityAt || chat.updatedAt * 1000))}</span>
          ${chat.unreadCount ? (chat.muted
            ? '<span class="muted-unread" aria-label="有未读消息"></span>'
            : `<span class="unread-badge">${chat.unreadCount > 99 ? "99+" : chat.unreadCount}</span>`) : ""}
        </span>
      </button>`).join("") || `<div class="list-status">${emptyText}</div>`;
    this.element.querySelectorAll("img").forEach((image) => {
      image.addEventListener("error", () => image.classList.add("is-broken"), { once: true });
      if (image.complete && image.naturalWidth === 0) image.classList.add("is-broken");
    });
    requestAnimationFrame(() => {
      this.element.scrollTop = Number(state.scrollPositions.chatList || 0);
    });
  }
}
