import { request } from "./api.js";

const page = document.querySelector("[data-control-page]")?.dataset.controlPage;
const $ = (selector) => document.querySelector(selector);

function text(value) {
  return String(value ?? "");
}

const interactionReasonLabels = Object.freeze({
  window_match_not_configured: "未配置虚拟机窗口匹配规则",
  window_match_pattern_invalid: "虚拟机窗口匹配规则无效",
  window_reader_failed: "读取虚拟机窗口失败",
  vm_window_not_found: "未找到匹配的虚拟机窗口",
  vm_window_ambiguous: "匹配到多个虚拟机窗口",
  login_state_probe_unconfigured: "未配置虚拟机登录状态探测",
  login_status_missing: "虚拟机登录状态文件不存在",
  login_status_stale: "虚拟机登录状态已过期",
  login_status_future: "虚拟机登录状态时间异常",
  login_session_mismatch: "虚拟机会话不匹配",
  login_status_malformed: "虚拟机登录状态格式无效",
  vm_logged_out: "虚拟机微信未登录",
  vm_activity_observation_failed: "读取虚拟机操作状态失败",
  vm_activity_event_invalid: "虚拟机操作状态无效",
  vm_window_observation_failed: "读取虚拟机窗口状态失败",
  vm_window_snapshot_invalid: "虚拟机窗口状态无效",
});

function interactionReasonLabel(reason) {
  return interactionReasonLabels[reason] || "状态未知";
}

function loginLabel(value) {
  if (value === true) return "已登录";
  if (value === false) return "未登录";
  return "未确认";
}

function windowStatusLabel(value) {
  return ({ ready: "可用", logged_out: "未登录", unknown: "未知" })[value] || "未知";
}

async function loadRules() {
  const payload = await request("/api/rules");
  const global = (payload.rules || []).find((rule) => rule.scope === "global");
  $("#global-instruction").value = global?.instruction || "";
  $("#global-reply-mode").value = global?.reply_mode || "auto";
  const list = $("#rule-list");
  list.replaceChildren();
  for (const rule of payload.rules || []) {
    const row = document.createElement("article");
    row.className = "rule-row";
    row.append(
      Object.assign(document.createElement("strong"), { textContent: `${rule.scope} · ${rule.target_id || "全局"}` }),
      Object.assign(document.createElement("span"), { textContent: rule.instruction || "默认规则" }),
      Object.assign(document.createElement("span"), { className: "muted", textContent: rule.reply_mode || "auto" }),
    );
    list.append(row);
  }
  if (!list.children.length) list.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "还没有规则" }));
  return payload;
}

async function initRules() {
  let payload;
  try { payload = await loadRules(); } catch (error) { $("#rules-status").textContent = error.message || "读取失败"; return; }
  $("#global-rule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const rules = (payload.rules || []).filter((rule) => rule.scope !== "global");
    rules.push({ id: "console-global", scope: "global", target_id: null, enabled: true, instruction: $("#global-instruction").value.trim(), reply_mode: $("#global-reply-mode").value, created_by: "user" });
    try {
      payload = await request("/api/rules/apply", { method: "POST", body: JSON.stringify({ revision: payload.revision, rules, routes: payload.routes || {} }) });
      $("#rules-status").textContent = "已保存";
      await loadRules();
    } catch (error) { $("#rules-status").textContent = error.message || "保存失败"; }
  });
  $("#reload-rules").addEventListener("click", () => loadRules().catch((error) => { $("#rules-status").textContent = error.message || "读取失败"; }));
}

let command = null;
async function initCommands() {
  $("#command-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = $("#command-status");
    status.textContent = "解析中";
    try {
      command = await request("/api/commands/preview", { method: "POST", body: JSON.stringify({ chatId: $("#command-chat-id").value.trim(), text: $("#command-input").value.trim() }) });
      const list = $("#command-operations");
      list.replaceChildren();
      for (const operation of command.operations || []) {
        const item = document.createElement("article");
        item.className = "operation-diff";
        item.append(Object.assign(document.createElement("strong"), { textContent: operation.summary || operation.op }), Object.assign(document.createElement("pre"), { textContent: `修改前\n${JSON.stringify(operation.before, null, 2)}\n\n修改后\n${JSON.stringify(operation.after, null, 2)}` }));
        list.append(item);
      }
      $("#command-risk").hidden = !command.requiresConfirmation;
      $("#command-preview").hidden = false;
      $("#command-risk-check").checked = false;
      status.textContent = "请检查预览";
    } catch (error) { status.textContent = error.message || "解析失败"; }
  });
  $("#command-apply").addEventListener("click", async () => {
    if (!command || (command.requiresConfirmation && !$("#command-risk-check").checked)) return;
    try {
      await request(`/api/commands/${encodeURIComponent(command.commandId)}/apply`, { method: "POST", body: JSON.stringify({ confirmHighRisk: Boolean(command.requiresConfirmation && $("#command-risk-check").checked) }) });
      $("#command-status").textContent = "已应用";
      $("#command-preview").hidden = true;
    } catch (error) { $("#command-status").textContent = error.message || "应用失败"; }
  });
}

async function initSettings() {
  const render = (payload) => {
    $("#runtime-paused").checked = Boolean(payload.settings?.paused);
    $("#runtime-reason").value = payload.settings?.reason || "";
    $("#runtime-status").textContent = `daemon：${payload.status?.activeWriter ? "运行中" : "未运行"} · 待处理会话：${payload.status?.pendingChats || 0} · 待处理消息：${payload.status?.pendingMessages || 0}`;
    const saved = payload.saved || {};
    const effective = payload.effective || {};
    const health = payload.health || "unknown";
    const error = saved.lastError || effective.lastError;
    $("#runtime-config-status").textContent = `配置：${health} · 已保存 v${saved.reloadToken ?? "-"} · 已生效 v${effective.reloadToken ?? "-"} · 模式：${effective.interactionMode || "-"} · 守卫：${effective.interactionEnforcement || "observe_only"} · 空闲阈值：${effective.idleTimeoutSeconds ?? "-"} 秒${error ? ` · ${error.message || error.code || "配置异常"}` : ""}`;
    const interaction = payload.status?.interaction || {};
    const windowState = interaction.window || {};
    const state = interaction.state || "PAUSED_UNKNOWN";
    const remaining = interaction.countdownRemainingSeconds ?? interaction.idleRemainingSeconds;
    const remainingText = remaining == null ? "-" : `${Math.ceil(Number(remaining))} 秒`;
    const enforcement = interaction.enforcement === "observe_only" ? "仅观察，未接入发送拦截" : (interaction.enforcement || "未知");
    const windowReason = windowState.reason || interaction.reason;
    $("#interaction-status").textContent = `人机状态：${state} · 执行模式：${enforcement} · 自动化：${interaction.canAutomate ? "可用" : "已暂停"} · 原因：${interactionReasonLabel(interaction.reason)} · 虚拟机窗口：${windowStatusLabel(windowState.status)} · 登录：${loginLabel(windowState.loggedIn)} · 前台：${windowState.isForeground ? "是" : "否"} · 倒计时：${remainingText}${interaction.leaseId ? ` · 租约：${interaction.leaseId}` : ""}`;
    $("#vm-diagnostics").textContent = `虚拟机诊断：窗口 ${windowStatusLabel(windowState.status)} · 登录 ${loginLabel(windowState.loggedIn)} · 原因：${interactionReasonLabel(windowReason)} · 最近观测：${windowState.observedAt || "未记录"}`;
    const transfer = payload.status?.transfer || {};
    $("#transfer-status").textContent = `文件事务：${transfer.stage || "idle"} · 来源：${transfer.source || "unknown"} · 项目数：${Number(transfer.itemCount || 0)} · 活动：${transfer.active ? "是" : "否"} · 结果：${transfer.outcome || "-"} · 执行模式：${transfer.enforcement === "observe_only" ? "仅观察" : (transfer.enforcement || "未知")}`;
  };
  try { render(await request("/api/runtime")); } catch (error) { $("#runtime-message").textContent = error.message || "读取失败"; }
  $("#runtime-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await request("/api/runtime", { method: "POST", body: JSON.stringify({ paused: $("#runtime-paused").checked, reason: $("#runtime-reason").value.trim() }) });
      render(await request("/api/runtime"));
      $("#runtime-message").textContent = "已保存";
    }
    catch (error) { $("#runtime-message").textContent = error.message || "保存失败"; }
  });
}

async function initAudit() {
  const load = async () => {
    const payload = await request("/api/audit");
    const list = $("#audit-list");
    list.replaceChildren();
    for (const event of payload.events || []) {
      const row = document.createElement("article");
      row.className = "audit-row";
      row.append(Object.assign(document.createElement("strong"), { textContent: event.kind }), Object.assign(document.createElement("span"), { textContent: `${event.target} · ${event.summary}` }), Object.assign(document.createElement("time"), { textContent: text(event.created_at) }));
      list.append(row);
    }
    if (!list.children.length) list.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "暂无审计记录" }));
  };
  await load().catch((error) => { $("#audit-list").textContent = error.message || "读取失败"; });
  $("#reload-audit").addEventListener("click", () => load().catch(() => {}));
}

if (page === "rules") initRules();
if (page === "commands") initCommands();
if (page === "settings") initSettings();
if (page === "audit") initAudit();
