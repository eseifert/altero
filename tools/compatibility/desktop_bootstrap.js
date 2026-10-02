// Installed only in disposable acceptance profiles. No hooks change sync behavior.
function startup(data) {
  Services.scriptloader.loadSubScript(data.rootURI + "dialogs.js", globalThis);
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
  await Zotero.Users.setCurrentUserID(config.user_id ?? 1);
  await Zotero.Users.setCurrentUsername(config.username ?? "compatibility");
  await Zotero.Sync.Data.Local.setAPIKey(config.key);
  const dialogs = watchAcceptanceDialogs(config.dialogs ?? []);
  const selectedLibrary = () => config.group_id
    ? Zotero.Groups.get(config.group_id)?.libraryID : Zotero.Libraries.userLibraryID;
  let libraryID = selectedLibrary();
  if (libraryID) await Zotero.Libraries.get(libraryID).waitForDataLoad("item");
  if (!libraryID && config.operations.length) throw new Error("Group must be discovered before editing");
  for (const operation of config.operations) {
    if (operation.action === "create") {
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
    } else throw new Error(`Unknown acceptance action ${operation.action}`);
  }
  if (config.sync) {
    const errors = [];
    await Zotero.Sync.Runner.sync({ background: true, ...(!config.group_id && libraryID ? {libraries: [libraryID]} : {}),
      ...(config.files ? {} : {fileLibraries: []}),
      fullTextLibraries: [], onError: error => errors.push(error.message) });
    if (errors.length) throw new Error(errors.join("; "));
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
  for (const item of items) {
    if (item.isFeedItem) continue;
    snapshot.push(item.toJSON({mode: "full", syncedStorageProperties: true}));
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
  const groups = Zotero.Groups.getAll().map(group => ({
    id: group.id, name: group.name, editable: group.editable,
    filesEditable: group.filesEditable, archived: group.archived
  }));
  dialogs.finish();
  await IOUtils.writeUTF8(config.result, JSON.stringify({ version: Zotero.version,
    items: snapshot, files, collections: collections.map(value => value.toJSON()),
    searches: searches.map(value => value.toJSON()), unsynced, groups, dialogs: dialogs.trace,
    storage_states, file_entries }));
  Services.startup.quit(Services.startup.eForceQuit);
}
