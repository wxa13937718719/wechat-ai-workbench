const initialState = {
  selectedChatId: null,
  chatPages: [],
  messagePages: {},
  drafts: {},
  scrollPositions: {},
  capabilities: {},
  updateCursor: 0,
};

function messageKey(message) {
  return `${message?.chatId || ""}:${message?.id || ""}`;
}

export function mergeMessages(existing = [], incoming = []) {
  const merged = new Map(existing.map((message) => [messageKey(message), message]));
  incoming.forEach((message) => merged.set(messageKey(message), message));
  return [...merged.values()].sort((left, right) => {
    const byTime = Number(left.timestamp || 0) - Number(right.timestamp || 0);
    return byTime || String(left.id || "").localeCompare(String(right.id || ""));
  });
}

export function mergeChatUpdates(chatPages = [], payload = {}) {
  const current = chatPages.flat();
  const byId = new Map(current.map((chat) => [String(chat.id), chat]));
  (payload.chats || []).forEach((chat) => {
    const id = String(chat.id || "");
    byId.set(id, { ...(byId.get(id) || {}), ...chat });
  });
  const requestedOrder = payload.chatOrder || [];
  const ordered = [];
  const consumed = new Set();
  requestedOrder.forEach((id) => {
    const key = String(id);
    if (!byId.has(key) || consumed.has(key)) return;
    ordered.push(byId.get(key));
    consumed.add(key);
  });
  current.forEach((chat) => {
    const key = String(chat.id);
    if (!consumed.has(key) && byId.has(key)) {
      ordered.push(byId.get(key));
      consumed.add(key);
    }
  });
  byId.forEach((chat, key) => {
    if (!consumed.has(key)) ordered.push(chat);
  });
  return [ordered];
}

export function createConversationStore(seed = {}) {
  let state = { ...initialState, ...seed };
  const subscriptions = new Map();

  function subscribe(scope, listener) {
    const listeners = subscriptions.get(scope) || new Set();
    listeners.add(listener);
    subscriptions.set(scope, listeners);
    return () => listeners.delete(listener);
  }

  function notify(scopes) {
    new Set(scopes).forEach((scope) => {
      (subscriptions.get(scope) || []).forEach((listener) => listener(state[scope], state));
    });
  }

  function update(patch) {
    const changed = Object.keys(patch).filter((key) => state[key] !== patch[key]);
    if (!changed.length) return state;
    state = { ...state, ...patch };
    notify(changed);
    return state;
  }

  function getState() {
    return state;
  }

  return { getState, update, subscribe, notify };
}

export const conversationStore = createConversationStore();
