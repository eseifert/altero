import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import vm from "node:vm";

const request = JSON.parse(readFileSync(0, "utf8"));
const requests = [], pauses = [];
const occurrences = new Map();
const base = new URL(request.baseURL);

class UnexpectedStatusException extends Error {
  constructor(xhr) {
    super(`HTTP ${xhr.status}`);
    this.xmlhttp = xhr;
  }
  is4xx() { return this.xmlhttp.status >= 400 && this.xmlhttp.status < 500; }
}
class BrowserOfflineException extends Error {}

function responseFacade(status, text, headers) {
  const normalized = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), String(v)]));
  return { status, responseText: text, getResponseHeader: name => normalized[name.toLowerCase()] ?? null };
}

async function httpRequest(method, uri, options = {}) {
  const url = new URL(uri);
  if (url.origin !== base.origin) throw new Error("Request escaped the test server");
  if (requests.length >= 100) throw new Error("Request limit exceeded (possible retry loop)");
  const count = (occurrences.get(url.pathname) ?? 0) + 1;
  occurrences.set(url.pathname, count);
  const fault = request.faults.find(f => (!f.path || f.path === url.pathname) && (f.occurrence ?? 1) === count);
  const headers = { ...options.headers };
  let body = options.body;
  if (options.compressBody) {
    body = gzipSync(body);
    headers["Content-Encoding"] = "gzip";
  }
  const trace = {
    method, url: uri, authenticated: !!headers["Zotero-API-Key"],
    headers: Object.fromEntries(Object.entries(headers).filter(([name]) => name.toLowerCase() !== "zotero-api-key")),
    body: options.body ?? null,
  };
  requests.push(trace);
  let status, text, responseHeaders;
  if (fault?.status) {
    ({ status, text = "", headers: responseHeaders = {} } = fault);
  } else {
    const response = await fetch(uri, { method, headers, body, redirect: "manual", signal: AbortSignal.timeout(10000) });
    status = response.status;
    text = await response.text();
    responseHeaders = Object.fromEntries(response.headers);
  }
  if (fault?.mutation === "drop-watermark") delete responseHeaders["last-modified-version"];
  if (fault?.mutation === "truncate-list") {
    const json = JSON.parse(text);
    text = JSON.stringify(Array.isArray(json) ? json.slice(0, 1) : Object.fromEntries(Object.entries(json).slice(0, 1)));
  }
  if (fault?.mutation === "drop-field") {
    const json = JSON.parse(text);
    delete json[fault.field];
    text = JSON.stringify(json);
  }
  trace.status = status;
  trace.responseHeaders = responseHeaders;
  if (fault?.mutation === "disconnect-after-write") throw new Error("Injected connection loss after server response");
  const xhr = responseFacade(status, text, responseHeaders);
  const accepted = options.successCodes ?? Array.from({ length: 100 }, (_, i) => i + 200);
  if (!accepted.includes(status)) throw new UnexpectedStatusException(xhr);
  return xhr;
}

const Zotero = {
  debug() {}, logError() {}, Sync: {}, Schema: { globalSchemaVersion: 32 },
  Prefs: { get: name => name === "sync.server.compressData" },
  DataObjectUtilities: { getObjectTypePlural: type => ({ item: "items", collection: "collections", search: "searches", tag: "tags" })[type] },
  HTTP: { request: httpRequest, UnexpectedStatusException, BrowserOfflineException,
    isWriteMethod: method => ["POST", "PATCH", "PUT", "DELETE"].includes(method) },
};
const context = vm.createContext({ Zotero });
let value = null, error = null;
try {
  vm.runInContext(request.source, context, { timeout: 1000 });
  const client = new Zotero.Sync.APIClient({
    baseURL: request.baseURL, apiVersion: 3, apiKey: request.key,
    caller: { start: fn => fn(), pause: ms => pauses.push(ms) },
  });
  if (!Object.hasOwn(Zotero.Sync.APIClient.prototype, request.method)
      || typeof client[request.method] !== "function") throw new Error("Unknown API method");
  value = await client[request.method](...request.args);
  if (Array.isArray(value)) value = await Promise.all(value);
} catch (e) {
  error = { message: e.message, status: e.xmlhttp?.status ?? null };
}
process.stdout.write(JSON.stringify({ value, error, requests, pauses }));
