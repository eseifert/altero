import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import vm from "node:vm";
import { runStorage } from "./storage_runtime.mjs";

const request = JSON.parse(readFileSync(0, "utf8"));
const requests = [], pauses = [], diagnostics = [];
const occurrences = new Map();
const base = new URL(request.baseURL);

class UnexpectedStatusException extends Error {
  constructor(xhr) {
    super(`HTTP ${xhr.status}`);
    this.xmlhttp = xhr;
    this.status = xhr.status;
  }
  is4xx() { return this.xmlhttp.status >= 400 && this.xmlhttp.status < 500; }
}
class BrowserOfflineException extends Error {}

function responseFacade(status, text, headers) {
  const normalized = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), String(v)]));
  return { status, responseText: text, getResponseHeader: name => normalized[name.toLowerCase()] ?? null,
    getAllResponseHeaders: () => JSON.stringify(normalized) };
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
  if (fault?.mutation === "empty-as-absent" && typeof body === "string") {
    const objects = JSON.parse(body);
    for (const object of objects) {
      for (const field of ["tags", "creators", "collections", "relations"]) {
        const value = object[field];
        if (value && typeof value === "object" && !Object.keys(value).length) delete object[field];
      }
    }
    body = JSON.stringify(objects);
  }
  const uncompressedBody = body;
  if (options.compressBody) {
    body = gzipSync(body);
    headers["Content-Encoding"] = "gzip";
  }
  const trace = {
    method, url: uri, authenticated: !!headers["Zotero-API-Key"],
    headers: Object.fromEntries(Object.entries(headers).filter(([name]) => name.toLowerCase() !== "zotero-api-key")),
    body: typeof uncompressedBody === "string" ? uncompressedBody : null,
  };
  requests.push(trace);
  let status, text, responseHeaders, bytes;
  if (fault?.status) {
    ({ status, text = "", headers: responseHeaders = {} } = fault);
  } else {
    const response = await fetch(uri, { method, headers, body, redirect: "manual", signal: AbortSignal.timeout(10000) });
    status = response.status;
    bytes = new Uint8Array(await response.arrayBuffer());
    text = new TextDecoder().decode(bytes);
    responseHeaders = Object.fromEntries(response.headers);
  }
  if (fault?.mutation === "drop-watermark") delete responseHeaders["last-modified-version"];
  if (fault?.mutation === "set-watermark") responseHeaders["last-modified-version"] = fault.value;
  if (fault?.mutation === "truncate-list") {
    const json = JSON.parse(text);
    text = JSON.stringify(Array.isArray(json) ? json.slice(0, 1) : Object.fromEntries(Object.entries(json).slice(0, 1)));
  }
  if (fault?.mutation === "drop-field") {
    const json = JSON.parse(text);
    delete json[fault.field];
    text = JSON.stringify(json);
  }
  if (fault?.mutation === "drop-data-field") {
    const json = JSON.parse(text);
    delete json.data[fault.field];
    text = JSON.stringify(json);
  }
  trace.status = status;
  trace.responseHeaders = responseHeaders;
  if (fault?.mutation === "disconnect-after-write") throw new Error("Injected connection loss after server response");
  const xhr = responseFacade(status, text, responseHeaders);
  xhr.bytes = bytes;
  const accepted = options.successCodes ?? Array.from({ length: 100 }, (_, i) => i + 200);
  if (!accepted.includes(status)) throw new UnexpectedStatusException(xhr);
  return xhr;
}

const Zotero = {
  debug() {}, logError: error => diagnostics.push(error?.message ?? String(error)), Sync: {}, Schema: { globalSchemaVersion: 32 },
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
  if (request.storage) {
    value = await runStorage(request.storage, context, client, httpRequest);
  } else {
  if (!Object.hasOwn(Zotero.Sync.APIClient.prototype, request.method)
      || typeof client[request.method] !== "function") throw new Error("Unknown API method");
  value = await client[request.method](...request.args);
  if (Array.isArray(value)) value = await Promise.all(value);
  }
} catch (e) {
  error = { message: e.message, status: e.xmlhttp?.status ?? null };
}
process.stdout.write(JSON.stringify({ value, error, requests, pauses, diagnostics }));
