import { request } from "./api.js";


function requestId() {
  return globalThis.crypto?.randomUUID?.() || `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class ComposerController {
  constructor({ element, editor, sendButton, tools, fileInput, store, timeline }) {
    this.element = element;
    this.editor = editor;
    this.sendButton = sendButton;
    this.tools = tools;
    this.fileInput = fileInput;
    this.store = store;
    this.timeline = timeline;
    this.chatId = null;
    this.composing = false;
    this.inFlight = new Map();
    this.bind();
    this.applyCapabilities();
    this.updateState();
  }

  bind() {
    this.editor.addEventListener("compositionstart", () => { this.composing = true; });
    this.editor.addEventListener("compositionend", () => { this.composing = false; });
    this.editor.addEventListener("input", () => {
      this.saveDraft();
      this.resize();
      this.updateState();
    });
    this.editor.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing || this.composing) return;
      event.preventDefault();
      this.send();
    });
    this.sendButton.addEventListener("click", () => this.send());
    document.addEventListener("wechat:retry-send", (event) => this.send({ ...event.detail, reusePending: true }));
    this.tools.querySelectorAll("[data-capability='sendFile'], [data-capability='sendImage']").forEach((button) => {
      button.addEventListener("click", () => {
        this.fileInput.accept = button.dataset.capability === "sendImage" ? "image/*" : "";
        this.fileInput.click();
      });
    });
  }

  setChat(chatId) {
    if (this.chatId) this.saveDraft();
    this.chatId = chatId;
    const draft = localStorage.getItem(this.draftKey(chatId)) || "";
    this.editor.value = draft;
    this.editor.disabled = !chatId;
    this.element.classList.toggle("is-disabled", !chatId);
    this.resize();
    this.updateState();
  }

  draftKey(chatId) {
    return `wechat-draft:${chatId}`;
  }

  saveDraft() {
    if (!this.chatId) return;
    const drafts = { ...this.store.getState().drafts, [this.chatId]: this.editor.value };
    this.store.update({ drafts });
    if (this.editor.value) localStorage.setItem(this.draftKey(this.chatId), this.editor.value);
    else localStorage.removeItem(this.draftKey(this.chatId));
  }

  clearDraftIfUnchanged(text) {
    if (this.editor.value.trim() !== text) return;
    this.editor.value = "";
    localStorage.removeItem(this.draftKey(this.chatId));
    const drafts = { ...this.store.getState().drafts };
    delete drafts[this.chatId];
    this.store.update({ drafts });
    this.resize();
    this.updateState();
  }

  resize() {
    this.editor.style.height = "0px";
    const editorHeight = Math.min(220, Math.max(34, this.editor.scrollHeight));
    this.editor.style.height = `${editorHeight}px`;
    const composerHeight = Math.min(320, Math.max(170, editorHeight + (this.tools.hidden ? 48 : 84)));
    this.element.closest(".chat-workspace")?.style.setProperty("--composer-height", `${composerHeight}px`);
  }

  applyCapabilities() {
    const capabilities = this.store.getState().capabilities;
    let visible = 0;
    this.tools.querySelectorAll("[data-capability]").forEach((button) => {
      const supported = Boolean(capabilities[button.dataset.capability]);
      button.hidden = !supported;
      if (supported) visible += 1;
    });
    this.tools.hidden = visible === 0;
    this.resize();
  }

  updateState() {
    const healthy = Boolean(this.store.getState().capabilities.sendText);
    this.sendButton.disabled = !this.chatId || !healthy || !this.editor.value.trim();
  }

  async recheck(text) {
    const payload = await request(`/api/chats/${encodeURIComponent(this.chatId)}/messages?limit=20`);
    return [...(payload.messages || [])].reverse().find((message) =>
      message.direction === "outgoing" && (message.display?.text ?? message.content) === text);
  }

  async send(options = {}) {
    const text = String(options.text ?? this.editor.value).trim();
    if (!this.chatId || !text) return;
    const clientRequestId = options.clientRequestId || requestId();
    if (this.inFlight.has(clientRequestId)) return;
    this.inFlight.set(clientRequestId, true);
    this.element.classList.add("is-sending");
    this.timeline.addPending(clientRequestId, text);
    try {
      let result = await request(`/api/chats/${encodeURIComponent(this.chatId)}/send`, {
        method: "POST",
        body: JSON.stringify({ text, clientRequestId, retryToken: options.retryToken || null }),
      });
      if (result.status === "unknown") {
        const verified = await this.recheck(text);
        if (verified) result = { ...result, status: "sent", message: verified, retryToken: null, retryable: false };
      }
      this.timeline.resolvePending(clientRequestId, result, text);
      if (result.status === "sent") this.clearDraftIfUnchanged(text);
    } catch (error) {
      this.timeline.resolvePending(clientRequestId, {
        status: "failed",
        retryToken: options.retryToken || null,
        errorMessage: error.message || "发送失败",
      }, text);
    } finally {
      this.inFlight.delete(clientRequestId);
      this.element.classList.toggle("is-sending", this.inFlight.size > 0);
      this.updateState();
    }
  }
}
