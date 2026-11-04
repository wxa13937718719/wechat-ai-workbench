import { requestBlob } from "./api.js";


function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function validHttpUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["http:", "https:"].includes(url.protocol) ? url : null;
  } catch (_error) {
    return null;
  }
}

function appendLinkifiedText(target, text) {
  const value = String(text || "");
  const pattern = /https?:\/\/[^\s]+/gu;
  let offset = 0;
  for (const match of value.matchAll(pattern)) {
    target.append(document.createTextNode(value.slice(offset, match.index)));
    const url = validHttpUrl(match[0]);
    if (url) {
      const link = element("a", "message-link", match[0]);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.append(element("span", "link-host", url.hostname));
      target.append(link);
    } else {
      target.append(document.createTextNode(match[0]));
    }
    offset = match.index + match[0].length;
  }
  target.append(document.createTextNode(value.slice(offset)));
}

function mediaEndpoint(message) {
  return `/api/chats/${encodeURIComponent(message.chatId)}/messages/${encodeURIComponent(message.id)}/media`;
}

function displayText(value) {
  const text = String(value || "");
  const disclosure = "——该内容由AI生成";
  return text.endsWith(`\n\n${disclosure}`) ? text.slice(0, -disclosure.length - 2) : text.endsWith(disclosure) ? text.slice(0, -disclosure.length).trimEnd() : text;
}

function openViewer(source, alt) {
  const viewer = element("div", "image-viewer");
  viewer.setAttribute("role", "dialog");
  viewer.setAttribute("aria-label", alt || "查看图片");
  const image = element("img");
  image.src = source;
  image.alt = alt || "";
  const close = element("button", "", "关闭");
  close.type = "button";
  close.setAttribute("aria-label", "关闭图片");
  close.addEventListener("click", () => viewer.remove());
  viewer.addEventListener("click", (event) => {
    if (event.target === viewer) viewer.remove();
  });
  viewer.append(image, close);
  document.body.append(viewer);
}

function renderMedia(message, kind) {
  const media = message.media?.[0] || {};
  const width = Number(media.width || 1);
  const height = Number(media.height || 1);
  const frame = element("div", "media-frame");
  frame.style.aspectRatio = `${Math.max(1, width)} / ${Math.max(1, height)}`;
  if (media.available === false) {
    frame.append(element("div", "media-unavailable", kind === "sticker" ? "表情暂不可用" : "图片暂不可用"));
    return frame;
  }

  async function load() {
    frame.className = "media-frame is-loading";
    frame.replaceChildren();
    try {
      let source;
      if (validHttpUrl(media.url)) {
        source = media.url;
      } else {
        const blob = await requestBlob(mediaEndpoint(message));
        source = URL.createObjectURL(blob);
      }
      const image = element("img");
      image.src = source;
      image.alt = message.display?.alt || (kind === "sticker" ? "表情包" : "图片");
      image.addEventListener("click", () => openViewer(source, image.alt));
      frame.className = "media-frame is-loaded";
      frame.append(image);
    } catch (error) {
      frame.className = "media-frame";
      if (error.retryable) {
        const errorBox = element("div", "media-error", error.message || "加载失败");
        const retry = element("button", "", "重试");
        retry.type = "button";
        retry.addEventListener("click", load);
        errorBox.append(retry);
        frame.append(errorBox);
      } else {
        frame.append(element("div", "media-unavailable", error.message || "媒体不可用"));
      }
    }
  }
  load();
  return frame;
}

function textRenderer(message) {
  const content = element("div", "message-content message-text");
  appendLinkifiedText(content, displayText(message.display?.text));
  return content;
}

function voiceRenderer(message, capabilities) {
  const button = element("button", "voice-control");
  button.type = "button";
  button.disabled = !capabilities.playVoice || message.media?.[0]?.available === false;
  const seconds = Math.max(1, Math.round(Number(message.display?.durationMs || 0) / 1000));
  button.append(element("span", "", "语音"), element("span", "", `${seconds}”`));
  if (!button.disabled) {
    button.addEventListener("click", async () => {
      const blob = await requestBlob(mediaEndpoint(message));
      const audio = new Audio(URL.createObjectURL(blob));
      await audio.play();
    });
  }
  return button;
}

function fileRenderer(message, capabilities) {
  const button = element("button", "file-control");
  button.type = "button";
  button.disabled = !capabilities.openMedia || message.media?.[0]?.available === false;
  const meta = element("span", "file-meta");
  meta.append(
    element("strong", "", message.display?.fileName || "文件"),
    element("span", "file-size", `${Number(message.display?.size || 0)} B`),
  );
  button.append(meta, element("span", "", "文件"));
  if (!button.disabled) {
    button.addEventListener("click", async () => {
      const blob = await requestBlob(mediaEndpoint(message));
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = message.display?.fileName || "文件";
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    });
  }
  return button;
}

function linkRenderer(message) {
  const url = validHttpUrl(message.display?.url);
  const card = element(url ? "a" : "div", "link-card");
  if (url) {
    card.href = url.href;
    card.target = "_blank";
    card.rel = "noopener noreferrer";
  }
  card.append(
    element("strong", "", message.display?.title || "链接"),
    element("span", "link-description", message.display?.description || ""),
    element("span", "link-source", message.display?.source || url?.hostname || ""),
  );
  return card;
}

function quoteRenderer(message) {
  const card = element("div", "quote-card");
  card.append(
    element("span", "", message.display?.text || ""),
    element("span", "quote-source", `${message.display?.quotedSender || ""}: ${message.display?.quotedText || ""}`),
  );
  return card;
}

function miniProgramRenderer(message) {
  const card = element("div", "mini-program-card");
  card.append(
    element("strong", "mini-program-title", message.display?.title || "小程序"),
    element("span", "mini-program-description", message.display?.description || "小程序消息"),
    element("span", "mini-program-source", message.display?.source || "微信小程序"),
  );
  const url = validHttpUrl(message.display?.url);
  if (url) {
    card.addEventListener("click", () => window.open(url.href, "_blank", "noopener,noreferrer"));
    card.classList.add("is-link");
  }
  return card;
}

export const renderers = {
  text: textRenderer,
  image: (message) => renderMedia(message, "image"),
  sticker: (message) => renderMedia(message, "sticker"),
  voice: voiceRenderer,
  file: fileRenderer,
  link: linkRenderer,
  quote: quoteRenderer,
  mini_program: miniProgramRenderer,
  system: (message) => element("span", "system-content", message.display?.text || ""),
  unsupported: (message) => element("span", "unsupported-message", `暂不支持此消息 (${message.display?.diagnosticCode || message.type})`),
};

export function renderMessageContent(message, capabilities = {}) {
  const kind = message.display?.kind || "unsupported";
  const renderer = renderers[kind] || renderers.unsupported;
  const content = renderer(message, capabilities);
  content.dataset.kind = kind;
  return content;
}
