import { request } from "./api.js";
import { renderMessageContent } from "./message-renderers.js";
import { mergeMessages } from "./store.js";


function initial(name) {
  return Array.from(String(name || "?").trim())[0] || "?";
}

function formatSeparator(timestamp) {
  const date = new Date(Number(timestamp || 0) * 1000);
  if (Number.isNaN(date.valueOf())) return "";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function needsSeparator(previous, current) {
  if (!previous) return true;
  return Number(current.timestamp || 0) - Number(previous.timestamp || 0) >= 300;
}

function avatar(sender) {
  const node = document.createElement("span");
  node.className = "avatar message-avatar";
  if (sender?.avatar) {
    const image = document.createElement("img");
    image.src = sender.avatar;
    image.alt = "";
    node.append(image);
  } else {
    node.textContent = initial(sender?.name);
  }
  return node;
}

function messageKey(message) {
  return `${message.chatId}:${message.id}`;
}

export class MessageListController {
  constructor({ element, indicator, store, capabilities }) {
    this.element = element;
    this.indicator = indicator;
    this.store = store;
    this.capabilities = capabilities;
    this.chat = null;
    this.messages = [];
    this.nextCursor = null;
    this.loadingOlder = false;
    this.newCount = 0;
    this.element.addEventListener("scroll", () => {
      const positions = { ...this.store.getState().scrollPositions };
      if (this.chat) positions[this.chat.id] = this.element.scrollTop;
      this.store.update({ scrollPositions: positions });
      if (this.element.scrollTop <= 24) this.loadOlder().catch(() => {});
    });
    this.indicator.addEventListener("click", () => this.scrollToBottom());
  }

  async load(chat) {
    this.chat = chat;
    this.messages = [];
    this.nextCursor = null;
    this.newCount = 0;
    this.updateIndicator();
    this.element.setAttribute("aria-busy", "true");
    const payload = await request(`/api/chats/${encodeURIComponent(chat.id)}/messages?limit=100`);
    if (this.chat?.id !== chat.id) return;
    this.messages = this.deduplicate(payload.messages || []);
    this.nextCursor = payload.nextCursor || null;
    this.savePage(payload);
    this.render();
    this.scrollToBottom();
    this.element.setAttribute("aria-busy", "false");
  }

  savePage(payload) {
    if (!this.chat) return;
    const messagePages = { ...this.store.getState().messagePages, [this.chat.id]: [payload] };
    this.store.update({ messagePages });
  }

  deduplicate(messages) {
    return mergeMessages([], messages);
  }

  firstVisibleAnchor() {
    const top = this.element.getBoundingClientRect().top;
    return [...this.element.querySelectorAll(".message-row")].find((node) => node.getBoundingClientRect().bottom > top) || null;
  }

  async loadOlder() {
    if (!this.chat || !this.nextCursor || this.loadingOlder) return;
    this.loadingOlder = true;
    const chatId = this.chat.id;
    const cursor = this.nextCursor;
    const existingIds = new Set(this.messages.map(messageKey));
    const anchor = this.firstVisibleAnchor();
    const anchorId = anchor?.dataset.messageId;
    const anchorTop = anchor?.getBoundingClientRect().top;
    try {
      const payload = await request(`/api/chats/${encodeURIComponent(chatId)}/messages?before=${encodeURIComponent(cursor)}&limit=100`);
      if (this.chat?.id !== chatId) return;
      this.messages = this.deduplicate([...(payload.messages || []), ...this.messages]);
      this.nextCursor = payload.nextCursor || null;
      this.savePage({ messages: this.messages, nextCursor: this.nextCursor });
      if (anchor && this.element.contains(anchor)) {
        this.prependOlderMessages(payload.messages || [], existingIds);
      } else {
        this.render();
      }
      if (anchorId && anchorTop !== undefined) {
        const restored = this.element.querySelector(`[data-message-id="${CSS.escape(anchorId)}"]`);
        if (restored) {
          const restore = () => {
            this.element.scrollTop += restored.getBoundingClientRect().top - anchorTop;
          };
          restore();
          requestAnimationFrame(restore);
        }
      }
    } finally {
      this.loadingOlder = false;
    }
  }

  append(chatId, messages) {
    if (!this.chat || this.chat.id !== chatId || !messages?.length) return;
    const atBottom = this.distanceFromBottom() <= 40;
    const before = new Set(this.messages.map(messageKey));
    this.messages = mergeMessages(this.messages, messages);
    const added = messages.filter((message) => !before.has(messageKey(message))).length;
    if (!added) return;
    this.savePage({ messages: this.messages, nextCursor: this.nextCursor });
    this.render();
    if (atBottom) {
      this.scrollToBottom();
    } else {
      this.newCount += added;
      this.updateIndicator();
    }
  }

  async refresh() {
    if (!this.chat) return;
    const chatId = this.chat.id;
    const payload = await request(`/api/chats/${encodeURIComponent(chatId)}/messages?limit=100`);
    if (this.chat?.id !== chatId) return;
    this.append(chatId, payload.messages || []);
  }

  addPending(clientRequestId, text) {
    if (!this.chat) return;
    const pending = {
      id: `client:${clientRequestId}`,
      clientRequestId,
      chatId: this.chat.id,
      type: 1,
      direction: "outgoing",
      timestamp: Math.floor(Date.now() / 1000),
      sender: { id: "self", name: "我", avatar: "" },
      display: { kind: "text", text },
      media: [],
      status: "sending",
    };
    const index = this.messages.findIndex((message) => message.clientRequestId === clientRequestId);
    if (index >= 0) this.messages[index] = pending;
    else this.messages.push(pending);
    this.render();
    this.scrollToBottom();
  }

  resolvePending(clientRequestId, result, fallbackText = "") {
    const index = this.messages.findIndex((message) => message.clientRequestId === clientRequestId);
    if (result.status === "sent" && result.message) {
      const verified = { ...result.message, status: "sent" };
      if (index >= 0) this.messages.splice(index, 1, verified);
      else this.messages.push(verified);
      this.messages = this.deduplicate(this.messages);
    } else {
      const failed = index >= 0 ? this.messages[index] : {
        id: `client:${clientRequestId}`,
        clientRequestId,
        chatId: this.chat?.id,
        type: 1,
        direction: "outgoing",
        timestamp: Math.floor(Date.now() / 1000),
        sender: { id: "self", name: "我", avatar: "" },
        display: { kind: "text", text: fallbackText },
        media: [],
      };
      failed.status = "failed";
      failed.retryToken = result.retryToken;
      failed.errorMessage = result.errorMessage || (result.status === "unknown" ? "发送结果未确认" : "发送失败");
      if (index < 0) this.messages.push(failed);
    }
    this.savePage({ messages: this.messages, nextCursor: this.nextCursor });
    this.render();
    window.lucide?.createIcons();
  }

  findOutgoingText(text) {
    return [...this.messages].reverse().find((message) =>
      message.direction === "outgoing" && (message.display?.text ?? message.content) === text && message.status !== "failed");
  }

  distanceFromBottom() {
    return this.element.scrollHeight - this.element.clientHeight - this.element.scrollTop;
  }

  scrollToBottom() {
    this.element.scrollTop = this.element.scrollHeight;
    this.newCount = 0;
    this.updateIndicator();
  }

  updateIndicator() {
    this.indicator.hidden = this.newCount === 0;
    this.indicator.textContent = this.newCount ? `${this.newCount} 条新消息` : "";
    this.indicator.setAttribute("aria-label", this.indicator.textContent || "新消息");
  }

  render() {
    this.element.replaceChildren();
    if (!this.messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "暂无消息";
      this.element.append(empty);
      return;
    }
    let previous = null;
    for (const message of this.messages) {
      if (needsSeparator(previous, message)) {
        const separator = document.createElement("div");
        separator.className = "date-separator";
        separator.textContent = formatSeparator(message.timestamp);
        this.element.append(separator);
      }
      this.element.append(this.renderMessage(message));
      previous = message;
    }
  }

  prependOlderMessages(messages, existingIds) {
    const fragment = document.createDocumentFragment();
    let previous = null;
    for (const message of messages) {
      if (existingIds.has(messageKey(message))) continue;
      if (needsSeparator(previous, message)) {
        const separator = document.createElement("div");
        separator.className = "date-separator";
        separator.textContent = formatSeparator(message.timestamp);
        fragment.append(separator);
      }
      fragment.append(this.renderMessage(message));
      previous = message;
    }
    this.element.prepend(fragment);
  }

  renderMessage(message) {
    const kind = message.display?.kind || "unsupported";
    if (kind === "system") {
      const system = document.createElement("div");
      system.className = "system-message";
      system.dataset.messageId = message.id;
      system.dataset.kind = kind;
      system.textContent = message.display?.text || "";
      return system;
    }
    const row = document.createElement("article");
    const outgoing = message.direction === "outgoing";
    row.className = `message-row ${outgoing ? "is-outgoing" : "is-incoming"}`;
    if (message.status === "sending") row.classList.add("is-pending");
    if (message.status === "failed") row.classList.add("is-failed");
    row.dataset.messageId = message.id;
    row.append(avatar(message.sender));

    const stack = document.createElement("div");
    stack.className = "message-stack";
    if (this.chat?.kind === "group" && !outgoing) {
      const name = document.createElement("span");
      name.className = "sender-name";
      name.textContent = message.sender?.name || "群成员";
      stack.append(name);
    }
    const bubble = document.createElement("div");
    bubble.className = `message-bubble has-tail${["image", "sticker"].includes(kind) ? " media-bubble" : ""}`;
    bubble.append(renderMessageContent(message, this.capabilities()));
    stack.append(bubble);
    if (message.status === "sending" || message.status === "failed") {
      const status = document.createElement("div");
      status.className = "message-status";
      if (message.status === "sending") {
        status.textContent = "发送中";
      } else {
        const label = document.createElement("span");
        label.textContent = message.errorMessage || "发送失败";
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "retry-send";
        retry.title = message.errorMessage || "发送失败，点击重试";
        retry.setAttribute("aria-label", "重试发送");
        const icon = document.createElement("i");
        icon.dataset.lucide = "rotate-cw";
        icon.setAttribute("aria-hidden", "true");
        retry.append(icon);
        retry.addEventListener("click", () => document.dispatchEvent(new CustomEvent("wechat:retry-send", { detail: {
          clientRequestId: message.clientRequestId,
          retryToken: message.retryToken,
          text: message.display?.text || "",
        } })));
        status.append(label, retry);
      }
      stack.append(status);
    }
    row.append(stack);
    return row;
  }
}
