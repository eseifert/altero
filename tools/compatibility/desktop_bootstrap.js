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
    } else if (operation.action === "collection") {
      const collection = new Zotero.Collection();
      collection.libraryID = libraryID;
      collection.key = operation.key;
      await collection.loadPrimaryData();
      collection.name = operation.name;
      await collection.saveTx();
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
  for (const item of items) {
    if (item.isFeedItem) continue;
    snapshot.push(item.toJSON({mode: "full", syncedStorageProperties: true}));
    if (config.files && item.isStoredFileAttachment()) {
      const path = await item.getFilePathAsync();
      files[item.key] = path && await IOUtils.exists(path)
        ? btoa(String.fromCharCode(...await IOUtils.read(path))) : null;
    }
  }
  const collections = libraryID ? await Zotero.Collections.getByLibrary(libraryID, true) : [];
  const searches = libraryID ? await Zotero.Searches.getAll(libraryID) : [];
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
    searches: searches.map(value => value.toJSON()), unsynced, groups, dialogs: dialogs.trace }));
  Services.startup.quit(Services.startup.eForceQuit);
}
