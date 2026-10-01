import { createHash } from "node:crypto";
import vm from "node:vm";

// These facades replace OS/filesystem/persistence. ZFS's transfer decisions stay original.
export async function runStorage(config, context, api, httpRequest) {
  const Zotero = context.Zotero;
  const bytes = Buffer.from(config.content, "base64");
  const filename = config.compressed ? "snapshot.html" : "research.pdf";
  const path = "/fixture/" + filename;
  let downloaded = null, processed = null;
  const item = {
    id: 1, key: config.key, libraryID: config.libraryID, libraryKey: config.key,
    version: 1, attachmentContentType: config.compressed ? "text/html" : "application/pdf",
    attachmentHash: config.md5, attachmentSyncedHash: config.syncedHash,
    attachmentModificationTime: config.localMtime ?? config.mtime,
    getFilePath: () => path, getFile: () => ({ path }), isImportedAttachment: () => true,
    async save() {}, async saveTx() {},
  };
  const fileRequest = { name: config.key, isFinished: () => false, onProgress() {}, setChannel() {} };
  const Result = class { constructor(value = {}) { Object.assign(this, value); } };
  Zotero.Sync.Storage = {
    Mode: {}, Result, defaultError: "File sync failed",
    Utilities: { getItemFromRequest: () => item },
    Local: { processDownload: async data => {
      if (!Number.isFinite(data.mtime) || !data.md5 || !downloaded) throw new Error("Incomplete download metadata");
      processed = { mtime: data.mtime, md5: data.md5, compressed: data.compressed, bytes: downloaded.toString("base64") };
      return new Result({ localChanges: true });
    } },
  };
  Zotero.Sync.Data = { Local: {
    getCacheObject: async () => null, markObjectAsUnsynced: async () => {},
    addObjectsToSyncQueue: async () => {},
  } };
  Zotero.DB = { executeTransaction: fn => fn() };
  Zotero.Items = { updateVersion: async (_ids, version) => { item.version = version; } };
  Zotero.Attachments = { hasMultipleFiles: async () => config.compressed };
  Zotero.Libraries = { get: () => ({ libraryType: config.kind, libraryTypeID: config.libraryID }) };
  Zotero.Utilities = { Internal: { md5Async: async () => createHash("md5").update(bytes).digest("hex") } };
  Zotero.Error = class extends Error {};
  Zotero.getTempDirectory = () => ({ path: "/fixture", append(name) { this.path += "/" + name; } });
  Zotero.File = { checkFileAccessError: error => { throw error; } };
  Zotero.HTTP.download = async uri => {
    const response = await httpRequest("GET", uri, {});
    downloaded = Buffer.from(response.bytes);
  };
  Object.assign(context, {
    Blob, File: { createFromFileName: async () => new Blob([bytes]) },
    PathUtils: { filename: p => p.split("/").pop() },
    OS: { Path: { join: (...parts) => parts.join("/") },
      File: { stat: async () => ({ size: bytes.length }), remove: async () => {}, setDates: async () => {} } },
    IOUtils: { write: async () => {}, exists: async () => config.localMtime !== null },
    Components: { utils: { importGlobalProperties() {}, reportError() {} } },
  });
  vm.runInContext(config.source, context, { timeout: 1000 });
  const mode = new Zotero.Sync.Storage.Mode.ZFS({ apiClient: api });
  mode._getRequestParams = (_libraryID, target) => ({ libraryType: config.kind, libraryTypeID: config.libraryID, target });
  let value;
  if (config.operation === "upload") {
    const params = await mode._getFileUploadParameters(item);
    value = params.exists ? params : await mode._uploadFile(fileRequest, item, params);
  } else if (config.operation === "authorize") {
    value = await mode._getFileUploadParameters(item);
  } else if (config.operation === "download") {
    value = await mode.downloadFile(fileRequest);
  } else throw new Error("Unknown storage operation");
  return { result: value, processed, item: {
    version: item.version, syncState: item.attachmentSyncState,
    mtime: item.attachmentSyncedModificationTime, md5: item.attachmentSyncedHash,
  } };
}
