import { request } from "./api.js";

const roles = [
  ["text_reply", "文本回复"],
  ["vision_reply", "图片理解"],
  ["instruction_parser", "指令解析"],
  ["safety_classifier", "安全判断"],
  ["summarizer", "上下文摘要"],
];

const state = { providers: [], routes: {} };
const $ = (selector) => document.querySelector(selector);

function optionLabel(provider, model) {
  return `${provider.name || provider.id} / ${model}`;
}

function modelsFor(provider) {
  return provider?.models?.length ? provider.models : ["（先点击发现模型）"];
}

function routePrimary(route) {
  if (route?.primary) return route.primary;
  if (route?.provider_id) return route;
  return {};
}

function renderProviders() {
  const list = $("#provider-list");
  list.replaceChildren();
  if (!state.providers.length) {
    list.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "还没有配置提供商" }));
    return;
  }
  for (const provider of state.providers) {
    const row = document.createElement("article");
    row.className = "provider-row";
    const title = document.createElement("div");
    title.className = "provider-main";
    title.innerHTML = `<strong></strong><span></span>`;
    title.querySelector("strong").textContent = provider.name || provider.id;
    title.querySelector("span").textContent = `${provider.id} · ${provider.kind}`;
    const meta = document.createElement("span");
    meta.className = "provider-model-count";
    meta.textContent = `${provider.models?.length || 0} 个模型`;
    const actions = document.createElement("div");
    actions.className = "provider-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "编辑";
    edit.addEventListener("click", () => fillProviderForm(provider));
    const discover = document.createElement("button");
    discover.type = "button";
    discover.textContent = "发现模型";
    discover.addEventListener("click", () => discoverModels(provider.id, discover));
    actions.append(edit, discover);
    row.append(title, meta, actions);
    list.append(row);
  }
}

function fillProviderForm(provider) {
  const form = $("#provider-form");
  for (const name of ["id", "name", "kind", "base_url"]) form.elements[name].value = provider[name] || "";
  form.elements.api_key.value = "";
  form.elements.id.focus();
}

function renderRoutes() {
  const list = $("#route-list");
  list.replaceChildren();
  if (!state.providers.length) {
    list.append(Object.assign(document.createElement("p"), { className: "muted", textContent: "请先添加提供商" }));
    return;
  }
  for (const [role, label] of roles) {
    const wrapper = document.createElement("label");
    wrapper.className = "route-row";
    wrapper.dataset.role = role;
    const name = document.createElement("span");
    name.textContent = label;
    const provider = document.createElement("select");
    provider.className = "route-provider";
    provider.setAttribute("aria-label", `${label}提供商`);
    for (const item of state.providers) provider.add(new Option(item.name || item.id, item.id));
    const model = document.createElement("select");
    model.className = "route-model";
    model.setAttribute("aria-label", `${label}模型`);
    const primary = routePrimary(state.routes[role]);
    provider.value = primary.provider_id || state.providers[0].id;
    const refreshModels = () => {
      const item = state.providers.find((candidate) => candidate.id === provider.value);
      model.replaceChildren(...modelsFor(item).map((entry) => new Option(entry, entry)));
      if (primary.model && modelsFor(item).includes(primary.model)) model.value = primary.model;
    };
    provider.addEventListener("change", refreshModels);
    wrapper.append(name, provider, model);
    list.append(wrapper);
    refreshModels();
  }
}

async function load() {
  try {
    const [providers, routes] = await Promise.all([request("/api/providers"), request("/api/routes")]);
    state.providers = providers.providers || [];
    state.routes = routes || {};
    renderProviders();
    renderRoutes();
  } catch (error) {
    $("#provider-status").textContent = error.message || "读取配置失败";
  }
}

async function discoverModels(id, button) {
  button.disabled = true;
  $("#provider-status").textContent = "正在读取模型列表";
  try {
    const result = await request(`/api/providers/${encodeURIComponent(id)}/discover`, { method: "POST" });
    const provider = state.providers.find((item) => item.id === id);
    if (provider) provider.models = result.models || [];
    renderProviders();
    renderRoutes();
    $("#provider-status").textContent = `已发现 ${result.models?.length || 0} 个模型`;
  } catch (error) {
    $("#provider-status").textContent = error.message || "模型发现失败";
  } finally {
    button.disabled = false;
  }
}

$("#provider-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  if (!body.api_key) delete body.api_key;
  try {
    await request("/api/providers", { method: "POST", body: JSON.stringify(body) });
    $("#provider-status").textContent = "已保存";
    await load();
  } catch (error) {
    $("#provider-status").textContent = error.message || "保存失败";
  }
});

$("#route-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const routes = {};
  for (const row of document.querySelectorAll(".route-row")) {
    routes[row.dataset.role] = {
      primary: { provider_id: row.querySelector(".route-provider").value, model: row.querySelector(".route-model").value },
      fallbacks: [],
    };
  }
  try {
    await request("/api/routes", { method: "POST", body: JSON.stringify({ routes }) });
    $("#route-status").textContent = "已保存，运行中的 AI 会在下一次调用时使用新路由";
  } catch (error) {
    $("#route-status").textContent = error.message || "保存失败";
  }
});

$("#refresh-providers").addEventListener("click", load);
load();
