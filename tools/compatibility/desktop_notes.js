// Drive the shipped note editor: open notes in the item pane, as a reader
// does, and let the editor itself write them.

// The item pane's editor, once it has loaded this note and drawn it.
async function openAcceptanceNote(item) {
  const window = Zotero.getMainWindow();
  await window.ZoteroPane.selectItem(item.id);
  const element = window.document.getElementById("zotero-note-editor");
  const deadline = Date.now() + 30000;
  while (true) {
    const instance = element.getCurrentInstance();
    if (instance && instance._item?.id === item.id) {
      await instance._initPromise;
      const core = instance._iframeWindow?.wrappedJSObject?._currentEditorInstance?._editorCore;
      if (core?.view) return { element, instance, core };
    }
    if (Date.now() > deadline) throw new Error(`The note editor never opened ${item.key}`);
    await Zotero.Promise.delay(100);
  }
}

// Wait until a save the editor started has reached the item, or until it is
// clear none will: an unchanged note is not saved at all.
async function settleAcceptanceNote(item, before) {
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    await Zotero.Promise.delay(200);
    if (item.note !== before && !Zotero.DB.inTransaction()) {
      await Zotero.Promise.delay(300);
      return;
    }
  }
}

// What the editor makes of each note when it saves it.
//
// `edit: "none"` marks the document changed without changing it, so the
// editor writes the note exactly as it would after an edit that was undone:
// the HTML is the note editor's own serialization of what it read. `edit:
// "append"` types `text` at the end of the last text block, as a reader would.
async function resaveAcceptanceNotes(operation, libraryID) {
  const notes = {};
  for (const key of operation.keys) {
    const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, key);
    const before = item.note;
    const { instance, core } = await openAcceptanceNote(item);
    if (instance._readOnly || core.readOnly) throw new Error(`The note editor opened ${key} read-only`);
    if (operation.edit === "append") {
      const view = core.view;
      const end = view.state.selection.constructor.atEnd(view.state.doc).from;
      view.dispatch(view.state.tr.insertText(operation.text, end));
    } else {
      core.docChanged = true;
    }
    instance.saveSync();
    await settleAcceptanceNote(item, before);
    notes[key] = item.note;
  }
  if (operation.path) await IOUtils.writeUTF8(operation.path, JSON.stringify(notes));
  return notes;
}

// Opening a note must not write it, and the editor must let it be changed.
async function viewAcceptanceNotes(operation, libraryID) {
  const seen = {};
  for (const key of operation.keys) {
    const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, key);
    const before = { note: item.note, version: item.version, synced: item.synced };
    const { instance, core } = await openAcceptanceNote(item);
    // Long enough for the editor's own debounce and any save it decides on.
    await Zotero.Promise.delay(2500);
    seen[key] = {
      readOnly: Boolean(instance._readOnly || core.readOnly),
      unsupportedSchema: Boolean(core.unsupportedSchema),
      written: item.note !== before.note || item.version !== before.version || item.synced !== before.synced,
    };
  }
  // Leave the note so nothing is saved on the way out.
  await Zotero.getMainWindow().ZoteroPane.selectItem(null);
  await IOUtils.writeUTF8(operation.path, JSON.stringify(seen));
}

// "Add Note from Annotations": the desktop builds the note's HTML itself.
async function noteFromAcceptanceAnnotations(operation, libraryID) {
  const attachment = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.attachment);
  const annotations = attachment.getAnnotations();
  if (!annotations.length) throw new Error("The attachment has no annotations to make a note from");
  const note = await Zotero.EditorInstance.createNoteFromAnnotations(annotations, {
    parentID: attachment.parentItemID,
    noSave: true,
  });
  // Unsaved and already loaded, so its key cannot be set: its HTML goes into
  // a note made with the key the scenario names it by, under the same parent.
  const named = new Zotero.Item("note");
  named.libraryID = libraryID;
  named.key = operation.key;
  await named.loadPrimaryData();
  named.parentID = attachment.parentItemID;
  named.setNote(note.getNote());
  await named.saveTx();
}
