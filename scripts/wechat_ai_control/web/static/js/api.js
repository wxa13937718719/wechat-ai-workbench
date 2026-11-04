export class ApiRequestError extends Error {
  constructor(error, status) {
    super(error?.message || `请求失败 (${status})`);
    this.name = "ApiRequestError";
    this.code = error?.code || "request_failed";
    this.retryable = Boolean(error?.retryable);
    this.details = error?.details || {};
    this.status = status;
  }
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new ApiRequestError(payload?.error, response.status);
  }
  return payload;
}

export async function requestBlob(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    throw new ApiRequestError(payload?.error, response.status);
  }
  return response.blob();
}
