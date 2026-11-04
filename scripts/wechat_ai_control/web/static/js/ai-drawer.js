import { request } from "./api.js";


const MODE_LABELS = {
  auto: "自动回复",
  manual: "人工处理",
  silent: "不自动回复",
};

function pretty(value) {
  if (value === null || value === undefined) return "无";
  if (typeof value === "string") return value || "无";
  return JSON.stringify(value, null, 2);
}

export class AiDrawerController {
  constructor({ drawer, openButton, closeButton, statusDot }) {
    this.drawer = drawer;
    this.openButton = openButton;
    this.closeButton = closeButton;
    this.statusDot = statusDot;
    this.chatId = null;
    this.context = null;
    this.command = null;
    this.lastFocused = null;
    this.loadVersion = 0;
    this.input = drawer.querySelector("#command-text");
    this.previewButton = drawer.querySelector("#command-preview");
    this.diff = drawer.querySelector("#ai-diff");
    this.operationList = drawer.querySelector("#ai-operation-list");
    this.riskConfirm = drawer.querySelector("#ai-risk-confirm");
    this.riskCheckbox = drawer.querySelector("#ai-risk-checkbox");
    this.applyButton = drawer.querySelector("#ai-apply-command");
    this.status = drawer.querySelector("#ai-drawer-status");
    this.grantButton = drawer.querySelector("#ai-grant-chat");
    this.revokeButton = drawer.querySelector("#ai-revoke-chat");
    this.bind();
  }

  bind() {
    this.openButton.addEventListener("click", () => this.open());
    this.closeButton.addEventListener("click", () => this.close());
    this.drawer.addEventListener("keydown", (event) => this.trapFocus(event));
    this.input.addEventListener("input", () => this.saveDraft());
    this.previewButton.addEventListener("click", () => this.preview());
    this.riskCheckbox.addEventListener("change", () => this.updateApplyState());
    this.drawer.querySelector("#ai-cancel-command").addEventListener("click", () => this.clearPreview());
    this.applyButton.addEventListener("click", () => this.apply());
    this.grantButton.addEventListener("click", () => this.setAiControl("grant"));
    this.revokeButton.addEventListener("click", () => this.setAiControl("revoke"));
  }

  draftKey(chatId) {
    return `wechat-ai-command:${chatId}`;
  }

  saveDraft() {
    if (!this.chatId) return;
    if (this.input.value) localStorage.setItem(this.draftKey(this.chatId), this.input.value);
    else localStorage.removeItem(this.draftKey(this.chatId));
  }

  setChat(chatId) {
    if (this.chatId) this.saveDraft();
    this.chatId = chatId;
    this.input.value = chatId ? localStorage.getItem(this.draftKey(chatId)) || "" : "";
    this.previewButton.disabled = !chatId;
    this.clearPreview();
    if (!this.drawer.hidden) this.loadContext();
  }

  async open() {
    this.lastFocused = document.activeElement;
    this.drawer.hidden = false;
    this.drawer.setAttribute("aria-hidden", "false");
    this.closeButton.focus();
    await this.loadContext();
  }

  close() {
    this.saveDraft();
    this.drawer.hidden = true;
    this.drawer.setAttribute("aria-hidden", "true");
    this.lastFocused?.focus?.();
  }

  trapFocus(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      this.close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...this.drawer.querySelectorAll("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href]")]
      .filter((element) => !element.hidden && element.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  async loadContext() {
    if (!this.chatId) {
      this.renderEmpty();
      return;
    }
    const version = ++this.loadVersion;
    this.status.textContent = "读取中";
    try {
      const context = await request(`/api/chats/${encodeURIComponent(this.chatId)}/ai-control`);
      if (version !== this.loadVersion) return;
      this.context = context;
      this.renderContext(context);
      this.status.textContent = "";
    } catch (error) {
      if (version !== this.loadVersion) return;
      this.status.textContent = error.message || "状态读取失败";
      this.setHealth("warning");
    }
  }

  renderEmpty() {
    this.drawer.querySelector("#ai-chat-name").textContent = "未选择会话";
    this.drawer.querySelector("#ai-reply-mode").textContent = "-";
    this.drawer.querySelector("#ai-unlock-state").textContent = "未解锁";
    this.drawer.querySelector("#ai-model-route").textContent = "-";
    this.drawer.querySelector("#ai-rule-summary").textContent = "-";
    this.drawer.querySelector("#ai-open-actions").replaceChildren();
    this.grantButton.disabled = true;
    this.revokeButton.disabled = true;
  }

  renderContext(context) {
    this.drawer.querySelector("#ai-chat-name").textContent = context.chatName || context.chatId;
    const unlock = this.drawer.querySelector("#ai-unlock-state");
    const sourceLabels = {
      manual_granted: "手动授权",
      contact_keyword: "对方关键词",
      manual_revoked: "手动撤销",
    };
    unlock.textContent = context.unlocked
      ? `已解锁 · ${sourceLabels[context.authorizationSource] || "已授权"}`
      : (sourceLabels[context.authorizationSource] || "未解锁");
    unlock.classList.toggle("is-unlocked", Boolean(context.unlocked));
    this.drawer.querySelector("#ai-reply-mode").textContent = MODE_LABELS[context.replyMode] || context.replyMode || "-";
    this.drawer.querySelector("#ai-model-route").textContent = context.modelRoute
      ? `${context.modelRoute.provider_id || ""} / ${context.modelRoute.model || ""}`.replace(/^ \/ | \/ $/g, "")
      : "未配置";
    this.drawer.querySelector("#ai-rule-summary").textContent = context.resolvedRule?.instruction || "默认规则";
    this.grantButton.disabled = context.authorizationSource === "manual_granted";
    this.revokeButton.disabled = context.authorizationSource === "manual_revoked";
    const actionList = this.drawer.querySelector("#ai-open-actions");
    actionList.replaceChildren();
    for (const action of context.openActions || []) {
      const notice = document.createElement("div");
      notice.className = "action-notice";
      notice.textContent = action.summary || action.kind;
      actionList.append(notice);
    }
    this.setHealth(context.health || "warning");
  }

  async setAiControl(action) {
    if (!this.chatId) return;
    this.grantButton.disabled = true;
    this.revokeButton.disabled = true;
    this.status.textContent = action === "grant" ? "正在授权" : "正在撤销授权";
    try {
      await request(`/api/chats/${encodeURIComponent(this.chatId)}/ai-control`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      this.status.textContent = action === "grant" ? "已手动授权" : "已手动撤销，关键词也不能重新解锁";
      await this.loadContext();
    } catch (error) {
      this.status.textContent = error.message || "AI 状态更新失败";
      this.renderContext(this.context || {});
    }
  }

  setHealth(health) {
    this.statusDot.className = `ai-status-dot is-${health}`;
  }

  async preview() {
    const text = this.input.value.trim();
    if (!this.chatId || !text) return;
    this.previewButton.disabled = true;
    this.status.textContent = "解析中";
    try {
      this.command = await request("/api/commands/preview", {
        method: "POST",
        body: JSON.stringify({ text, chatId: this.chatId }),
      });
      this.renderDiff(this.command);
      this.status.textContent = "";
    } catch (error) {
      this.status.textContent = error.message || "解析失败";
    } finally {
      this.previewButton.disabled = false;
    }
  }

  renderDiff(command) {
    this.operationList.replaceChildren();
    for (const operation of command.operations || []) {
      const section = document.createElement("section");
      section.className = "operation-diff";
      const title = document.createElement("h3");
      title.textContent = operation.summary || operation.op;
      const values = document.createElement("div");
      values.className = "operation-values";
      const before = document.createElement("pre");
      before.textContent = `修改前\n${pretty(operation.before)}`;
      const after = document.createElement("pre");
      after.textContent = `修改后\n${pretty(operation.after)}`;
      values.append(before, after);
      section.append(title, values);
      this.operationList.append(section);
    }
    this.riskCheckbox.checked = false;
    this.riskConfirm.hidden = !command.requiresConfirmation;
    this.diff.hidden = false;
    this.updateApplyState();
  }

  updateApplyState() {
    this.applyButton.disabled = !this.command || (this.command.requiresConfirmation && !this.riskCheckbox.checked);
  }

  clearPreview() {
    this.command = null;
    this.diff.hidden = true;
    this.operationList.replaceChildren();
    this.riskCheckbox.checked = false;
  }

  async apply() {
    if (!this.command || this.applyButton.disabled) return;
    this.applyButton.disabled = true;
    try {
      await request(`/api/commands/${encodeURIComponent(this.command.commandId)}/apply`, {
        method: "POST",
        body: JSON.stringify({ confirmHighRisk: Boolean(this.command.requiresConfirmation && this.riskCheckbox.checked) }),
      });
      this.status.textContent = "已应用";
      this.clearPreview();
      await this.loadContext();
    } catch (error) {
      this.status.textContent = error.message || "应用失败";
      this.updateApplyState();
    }
  }
}
