// Observe the original streamer and sync runner over a real WebSocket.
async function watchAcceptanceStreaming(operation, libraryID) {
  const wait = async (predicate, description) => {
    const deadline = Date.now() + 60000;
    while (!await predicate()) {
      if (Date.now() > deadline) throw new Error(description);
      await Zotero.Promise.delay(50);
    }
  };
  Zotero.Prefs.set("streaming.url", operation.url);
  Zotero.Prefs.set("sync.autoSync", true);
  Zotero.Prefs.set("streaming.enabled", true);
  try {
    const streamer = Zotero.Streamer;
    await wait(() => streamer._ready && streamer._subscriptions.has("sync"), "Initial streaming subscription failed");
    const original = streamer._socket;
    await IOUtils.writeUTF8(operation.ready, "subscribed");
    await wait(() => original.readyState === original.CLOSED, "Original socket was not closed");
    const closedAt = Date.now();
    await wait(() => streamer._socket !== original && streamer._ready && streamer._subscriptions.has("sync"), "Desktop did not reconnect and resubscribe");
    const elapsed = Date.now() - closedAt;
    if (elapsed < 1800) throw new Error("Reconnect bypassed the original two-second retry delay");
    await IOUtils.writeUTF8(operation.reconnected, JSON.stringify({elapsed}));
    await wait(async () => {
      const item = await Zotero.Items.getByLibraryAndKeyAsync(libraryID, operation.key);
      return item?.getField("title") === operation.title && !Zotero.Sync.Runner.syncInProgress;
    }, "Notification did not drive automatic desktop sync");
    return {elapsed, automaticSync: true};
  } finally {
    Zotero.Prefs.set("streaming.enabled", false);
    Zotero.Prefs.set("sync.autoSync", false);
  }
}
