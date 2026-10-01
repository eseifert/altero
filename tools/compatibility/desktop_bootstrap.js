// Installed only in disposable acceptance profiles. No hooks change sync behavior.
function startup() {
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
  const config = JSON.parse(await IOUtils.readUTF8(Services.prefs.getStringPref("extensions.altero.acceptance.config")));
  if (Zotero.version !== config.version) throw new Error(`Expected desktop ${config.version}, got ${Zotero.version}`);
  await Zotero.Users.setCurrentUserID(1);
  await Zotero.Users.setCurrentUsername("compatibility");
  await Zotero.Sync.Data.Local.setAPIKey(config.key);
  const libraryID = Zotero.Libraries.userLibraryID;
  await Zotero.Libraries.userLibrary.waitForDataLoad("item");
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
    } else throw new Error(`Unknown acceptance action ${operation.action}`);
  }
  if (config.sync) {
    const errors = [];
    await Zotero.Sync.Runner.sync({ background: true, libraries: [libraryID],
      fullTextLibraries: [], onError: error => errors.push(error.message) });
    if (errors.length) throw new Error(errors.join("; "));
  }
  const items = await Zotero.Items.getAll(libraryID, false, true);
  const snapshot = [];
  for (const item of items) {
    if (item.isFeedItem) continue;
    snapshot.push(item.toJSON());
  }
  await IOUtils.writeUTF8(config.result, JSON.stringify({ version: Zotero.version, items: snapshot }));
  Services.startup.quit(Services.startup.eForceQuit);
}
