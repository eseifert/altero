// Installed only in disposable acceptance profiles. No hooks change sync behavior.
function startup(data) {
  Services.scriptloader.loadSubScript(data.rootURI + "dialogs.js", globalThis);
  Services.scriptloader.loadSubScript(data.rootURI + "streaming.js", globalThis);
  Services.scriptloader.loadSubScript(data.rootURI + "reader.js", globalThis);
  Zotero.initializationPromise.then(runAcceptance).catch(writeFailure);
}
function shutdown() {}
function install() {}
function uninstall() {}

async function writeFailure(error) {
  const config = JSON.parse(await IOUtils.readUTF8(Services.prefs.getStringPref("extensions.altero.acceptance.config")));
  await IOUtils.writeUTF8(config.result, JSON.stringify({ error: error.message, stack: error.stack }));
  Services.startup.quit(Services.startup.eForceQuit);
}

async function runAcceptance() {
  await Zotero.uiReadyPromise;
  await Zotero.Schema.schemaUpdatePromise;
  const config = JSON.parse(await IOUtils.readUTF8(Services.prefs.getStringPref("extensions.altero.acceptance.config")));
  if (Zotero.version !== config.version) throw new Error(`Expected desktop ${config.version}, got ${Zotero.version}`);
  if (!Zotero.Users.getCurrentUserID()) {
    await Zotero.Users.setCurrentUserID(config.user_id ?? 1);
    await Zotero.Users.setCurrentUsername(config.username ?? "compatibility");
  }
  if (config.key !== null) await Zotero.Sync.Data.Local.setAPIKey(config.key);
  const dialogs = watchAcceptanceDialogs(config.dialogs ?? []);
  const selectedLibrary = () => config.group_id
    ? Zotero.Groups.get(config.group_id)?.libraryID : Zotero.Libraries.userLibraryID;
  let libraryID = selectedLibrary();
  let streaming;
  let reader;
  if (libraryID) await Zotero.Libraries.get(libraryID).waitForDataLoad("item");
  if (!libraryID && config.operations.length) throw new Error("Group must be discovered before editing");
  for (const operation of config.operations) {
    if (operation.action === "reader-open") {
      reader = await observeAcceptanceReader(operation, libraryID);
    } else if (operation.action === "stream-watch") {
      streaming = await watchAcceptanceStreaming(operation, libraryID);
    } else if (operation.action === "login-start") {
      const session = await Zotero.Sync.Runner.startLoginSession();
      await IOUtils.writeUTF8(operation.path, JSON.stringify(session));
    } else if (operation.action === "login-finish") {
      const session = JSON.parse(await IOUtils.readUTF8(operation.path));
      const result = await Zotero.Sync.Runner.checkLoginSession(session.sessionToken);
      if (result.status !== "completed" || !result.apiKey) throw new Error("Login did not hand out a key");
    } else if (operation.action === "login-cancel") {
      const session = JSON.parse(await IOUtils.readUTF8(operation.path));
      const client = Zotero.Sync.Runner.getAPIClient();
      await client.cancelLoginSession(session.sessionToken);
    } else if (operation.action === "login-check") {
      const session = JSON.parse(await IOUtils.readUTF8(operation.path));
      let expired = false;
      let result;
      try {result = await Zotero.Sync.Runner.checkLoginSession(session.sessionToken);}
      catch (error) {if (error.expired) expired = true; else throw error;}
      if (operation.expected === "expired" ? !expired : expired || result.status !== operation.expected) {
        throw new Error("Login session outcome differed from the expected desktop decision");
      }
    } else if (operation.action === "revoke-key") {
      const client = Zotero.Sync.Runner.getAPIClient({apiKey: await Zotero.Sync.Data.Local.getAPIKey()});
      await client.deleteAPIKey();
    } else if (operation.action === "create") {
      const item = new Zotero.Item();
      item.libraryID = libraryID;
      item.key = operation.key;
      await item.loadPrimaryData();
      item.fromJSON(operation.data ?? { itemType: operation.itemType ?? "book", title: "Über 東京" });
      await item.saveTx();
    } else if (operation.action === "edit") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      for (const [field, value] of Object.entries(operation.fields)) item.setField(field, value);
      await item.saveTx();
    } else if (operation.action === "json") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      item.fromJSON({...item.toJSON({mode: "full", syncedStorageProperties: true}), ...operation.data});
      await item.saveTx();
    } else if (operation.action === "trash" || operation.action === "restore") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      item.deleted = operation.action === "trash";
      await item.saveTx();
    } else if (operation.action === "delete") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      await item.eraseTx();
    } else if (operation.action === "attach") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      await Zotero.Attachments.importFromFile({ file: operation.path, parentItemID: item.id });
    } else if (operation.action === "snapshot") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      await Zotero.Attachments.importSnapshotFromFile({file: operation.path, parentItemID: item.id,
        title: "Snapshot", url: "https://example.org/disposable", contentType: "text/html", charset: "UTF-8"});
    } else if (operation.action === "download-file") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      await Zotero.Sync.Runner.downloadFile(item);
    } else if (operation.action === "rename-file") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      if (await item.renameAttachmentFile(operation.name) !== true) throw new Error("Attachment rename failed");
    } else if (operation.action === "index") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      await Zotero.FullText.indexItems([item.id]);
    } else if (operation.action === "replace-file" || operation.action === "remove-file") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      const path = await item.getFilePathAsync();
      if (!path) throw new Error("Attachment has no local path");
      if (operation.action === "remove-file") await IOUtils.remove(path);
      else {
        await IOUtils.write(path, await IOUtils.read(operation.path));
        await IOUtils.setModificationTime(path, operation.mtime);
      }
      await Zotero.Sync.Storage.Local.checkForUpdatedFiles(libraryID, [item.id]);
    } else if (operation.action === "collection") {
      let collection = Zotero.Collections.getByLibraryAndKey(libraryID, operation.key);
      if (!collection) {
        collection = new Zotero.Collection();
        collection.libraryID = libraryID;
        collection.key = operation.key;
        await collection.loadPrimaryData();
      }
      if (operation.name !== undefined) collection.name = operation.name;
      if (operation.parent !== undefined) collection.parentKey = operation.parent;
      await collection.saveTx();
    } else if (operation.action === "search") {
      let search = Zotero.Searches.getByLibraryAndKey(libraryID, operation.key);
      if (!search) {
        search = new Zotero.Search();
        search.libraryID = libraryID;
        search.key = operation.key;
        await search.loadPrimaryData();
      }
      if (search.id) await search.loadDataType("conditions");
      search.fromJSON({name: operation.name, conditions: operation.conditions});
      await search.saveTx();
    } else if (operation.action === "file") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      item.setCollections(operation.collections);
      await item.saveTx();
    } else if (operation.action === "setting") {
      if (operation.value === null) await Zotero.SyncedSettings.clear(libraryID, operation.name);
      else await Zotero.SyncedSettings.set(libraryID, operation.name, operation.value);
    } else if (operation.action === "tag-color") {
      await Zotero.Tags.setColor(libraryID, operation.name, operation.color, operation.position);
    } else if (operation.action === "related") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      const other = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.other);
      item.addRelatedItem(other);
      other.addRelatedItem(item);
      await Zotero.DB.executeTransaction(async () => {await item.save(); await other.save();});
    } else if (operation.action === "merge") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      const others = await Promise.all(operation.others.map(key => Zotero.Items.getByLibraryAndKeyAsync(libraryID, key)));
      const {mergeItems} = ChromeUtils.importESModule("chrome://zotero/content/mergeItems.mjs");
      await mergeItems(item, others);
    } else if (operation.action === "publish" || operation.action === "withdraw") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      if (operation.action === "publish") await Zotero.Items.addToPublications([item], operation.options);
      else await Zotero.Items.removeFromPublications([item]);
    } else if (operation.action === "copy-to-group") {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      const target = Zotero.Groups.get(operation.group_id);
      if (!target) throw new Error("Copy destination was not discovered");
      const view = Zotero.getActiveZoteroPane().collectionsView;
      const row = view.getRow(view.getRowIndexByID("L" + target.libraryID));
      if (!row || !row.isGroup()) throw new Error("Copy destination has no actual group tree row");
      await Zotero.DB.executeTransaction(() => view._copyItem({item, targetLibraryID: target.libraryID, targetTreeRow: row,
        options: {tags: true, childNotes: true, childFileAttachments: true, childLinks: true, annotations: true}}));
    } else throw new Error(`Unknown acceptance action ${operation.action}`);
  }
  if (config.sync) {
    const errors = [];
    let completed = false;
    let cancelled = false;
    const cancellation = (async () => {
      if (!config.cancel_path) return;
      while (!completed) {
        if (await IOUtils.exists(config.cancel_path)) {
          Zotero.Sync.Runner.stop();
          cancelled = true;
          await IOUtils.writeUTF8(config.cancel_path + ".ack", "stopped");
          return;
        }
        await Zotero.Promise.delay(50);
      }
    })();
    if (config.reset && !["from-server", "to-server"].includes(config.reset)) throw new Error("Unknown sync reset mode");
    if (config.reset === "from-server") await Zotero.Sync.Data.Local.resetUnsyncedLibraryData(libraryID);
    try {
      await Zotero.Sync.Runner.sync({ background: true, ...(!config.group_id && !config.all_libraries && libraryID ? {libraries: [libraryID]} : {}),
      ...(config.reset === "to-server" ? {resetMode: Zotero.Sync.Runner.RESET_MODE_TO_SERVER} : {}),
      ...(config.files ? {} : {fileLibraries: []}),
      ...(config.fulltext ? {} : {fullTextLibraries: []}), onError: error => errors.push(error) });
    } finally {
      completed = true;
      await cancellation;
    }
    if (config.cancel_path && !cancelled) throw new Error("Requested user cancellation never stopped a real sync");
    if (config.expected_error_message) {
      if (errors.length !== 1 || errors[0].message !== config.expected_error_message) {
        throw new Error(`Expected ${config.expected_error_message}, got ${errors.map(error => error.message)}`);
      }
    } else if (config.expected_error) {
      if (typeof Zotero.Error[config.expected_error] !== "number" || errors.length !== 1 || errors[0].error !== Zotero.Error[config.expected_error]) {
        throw new Error(`Expected ${config.expected_error}, got ${errors.map(error => error.message)}`);
      }
    } else if (config.expected_file_sync_error) {
      if (errors.length !== 1 || errors[0].message !== Zotero.Sync.Storage.defaultError) {
        throw new Error(`Expected one storage failure, got ${errors.map(error => error.message)}`);
      }
    } else if (config.expected_upload_errors) {
      const observed = errors.map(error => ({code: error.code, key: error.object?.key}));
      const sorted = values => values.sort((a, b) => a.key.localeCompare(b.key));
      if (JSON.stringify(sorted(observed)) !== JSON.stringify(sorted(config.expected_upload_errors))) {
        throw new Error(`Unexpected upload errors: ${JSON.stringify(observed)}`);
      }
    } else if (errors.length) throw new Error(errors.map(error => error.message).join("; "));
    if (config.fulltext) {
      const deadline = Date.now() + 10000;
      do {
        await Zotero.FullText.processSyncedContentNow();
        if (!await Zotero.DB.valueQueryAsync("SELECT COUNT(*) FROM fulltextItems WHERE synced=2")) break;
        if (Date.now() > deadline) throw new Error("Downloaded full-text content was not indexed");
        await Zotero.Promise.delay(100);
      } while (true);
    }
  }
  libraryID = selectedLibrary();
  if (libraryID) await Zotero.Libraries.get(libraryID).waitForDataLoad("item");
  const items = libraryID ? await Zotero.Items.getAll(libraryID, false, true) : [];
  const snapshot = [];
  const files = {};
  async function encodedFile(path) {
    const bytes = await IOUtils.read(path);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 32768) {
      binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
    }
    return btoa(binary);
  }
  const storage_states = {};
  const file_entries = {};
  const fulltext = {};
  for (const item of items) {
    if (item.isFeedItem) continue;
    snapshot.push(item.toJSON({mode: "full", syncedStorageProperties: true}));
    if (item.isAttachment()) {
      const row = await Zotero.DB.rowQueryAsync(
        "SELECT version, synced, indexedChars, totalChars, indexedPages, totalPages FROM fulltextItems WHERE itemID=?", item.id);
      if (row) {
        const matches = [];
        for (const term of config.fulltext_terms ?? []) {
          if ((await Zotero.FullText.findItemsWithContent(term, libraryID, [item.id])).includes(item.id)) matches.push(term);
        }
        fulltext[item.key] = Object.fromEntries(
          ["version", "synced", "indexedChars", "totalChars", "indexedPages", "totalPages"].map(field => [field, row[field]]));
        fulltext[item.key].matches = matches;
      }
    }
    if (config.files && item.isStoredFileAttachment()) {
      storage_states[item.key] = Object.entries(Zotero.Sync.Storage.Local)
        .find(([name, value]) => name.startsWith("SYNC_STATE_") && value === item.attachmentSyncState)?.[0]
        .slice("SYNC_STATE_".length).toLowerCase() ?? "unknown";
      const path = await item.getFilePathAsync();
      files[item.key] = path && await IOUtils.exists(path)
        ? await encodedFile(path) : null;
      const entries = {};
      if (path && await IOUtils.exists(path)) {
        const directory = PathUtils.parent(path);
        async function visit(folder) {
          for (const entry of await IOUtils.getChildren(folder)) {
            if (PathUtils.filename(entry).startsWith(".")) continue;
            if ((await IOUtils.stat(entry)).type === "directory") await visit(entry);
            else entries[entry.slice(directory.length + 1)] = await encodedFile(entry);
          }
        }
        await visit(directory);
      }
      file_entries[item.key] = entries;
    }
  }
  const collections = libraryID ? await Zotero.Collections.getByLibrary(libraryID, true) : [];
  const searches = libraryID ? await Zotero.Searches.getAll(libraryID) : [];
  for (const search of searches) await search.loadDataType("conditions");
  const unsynced = {};
  if (libraryID) for (const type of ["item", "collection", "search"]) {
    unsynced[type] = await Zotero.Sync.Data.Local.getUnsynced(type, libraryID);
  }
  const settings = {};
  if (libraryID) {
    unsynced.setting = await Zotero.SyncedSettings.getUnsynced(libraryID);
    for (const name of await Zotero.DB.columnQueryAsync("SELECT setting FROM syncedSettings WHERE libraryID=?", libraryID)) {
      settings[name] = {value: Zotero.SyncedSettings.get(libraryID, name), version: Number(Zotero.SyncedSettings.getMetadata(libraryID, name).version)};
    }
  }
  const tag_colors = libraryID ? Object.fromEntries(Zotero.Tags.getColors(libraryID)) : {};
  const groups = Zotero.Groups.getAll().map(group => ({
    id: group.id, name: group.name, editable: group.editable,
    filesEditable: group.filesEditable, archived: group.archived
  }));
  dialogs.finish();
  await IOUtils.writeUTF8(config.result, JSON.stringify({ version: Zotero.version,
    items: snapshot, files, collections: collections.map(value => value.toJSON()),
    searches: searches.map(value => value.toJSON()), unsynced, groups, dialogs: dialogs.trace,
    storage_states, file_entries, fulltext, settings, tag_colors, streaming, reader, user_id: Zotero.Users.getCurrentUserID() }));
  Services.startup.quit(Services.startup.eForceQuit);
}
