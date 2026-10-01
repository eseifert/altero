// Fixtures replace persistence and HTTP, while original functions make decisions.
export function adapterScript(name) {
  if (name === "pure") return "selected(...args)";
  if (name === "streamer") return `(async () => {
    const syncs = [], errors = [], delays = [];
    class WebSocket { constructor() {} }
    globalThis.WebSocket = WebSocket;
    globalThis.Zotero = {
      debug() {}, logError: error => errors.push(error),
      URI: {getPathLibrary: topic => fixtures.libraries[topic]},
      Sync: {Runner: {sync: async options => syncs.push(options)},
        Data: {Local: {filterSkippedLibraries: libraries => libraries.filter(l => !l.skipped)}}},
      Schema: {onUpdateNotification: async () => {}},
      Utilities: {Internal: {delayGenerator: function* (intervals) {
        for (const ms of intervals) { delays.push(ms); yield Promise.resolve(); }
      }}},
    };
    const receiver = {url: 'ws://disposable.invalid', _subscriptions: new Set(),
      _topicListeners: new Map(), _hideAPIKey: dependencies.streamer_hide_key, updates: 0,
      _update() { this.updates++; }};
    await selected.call(receiver);
    for (const message of fixtures.messages) {
      await receiver._socket.onmessage({data: JSON.stringify(message)});
    }
    if (fixtures.close) await receiver._socket.onclose(fixtures.close);
    return {syncs, errors, delays, updates: receiver.updates,
      ready: receiver._ready, subscriptions: [...receiver._subscriptions]};
  })()`;
  if (name === "api_versions") return `(async () => {
    const requests = [];
    let params;
    globalThis.Zotero = {
      debug() {},
      DataObjectUtilities: {
        getObjectTypePlural: type => ({item: 'items', collection: 'collections', search: 'searches'})[type],
      },
    };
    const receiver = {
      buildRequestURI: value => { params = value; return '/captured-response'; },
      _parseJSON: dependencies.parse_json,
      makeRequest: async (method, uri, options) => {
        requests.push({method, uri, options, params});
        return {
          status: fixtures.status, responseText: fixtures.text,
          getResponseHeader: name => fixtures.headers[name.toLowerCase()] ?? null,
        };
      },
    };
    const value = await selected.call(receiver, ...args);
    return {value, requests};
  })()`;
  if (name !== "group_refresh") throw new Error(`Unknown adapter: ${name}`);
  return `(async () => {
    const known = new Map();
    const fetched = [];
    class Group {
      archived = false;
      get libraryID() { return this.id; }
      fromJSON(json, id) { dependencies.group_from_json.call(this, json, id); }
      async saveTx() { known.set(this.id, this); }
      async eraseTx() { known.delete(this.id); }
    }
    for (const cached of fixtures.cached) {
      known.set(cached.id, Object.assign(new Group(), cached));
    }
    globalThis.Zotero = {
      debug() {}, Group,
      Users: { getCurrentUserID: () => fixtures.keyInfo.userID },
      Libraries: {
        userLibraryID: 1,
        get: id => ({libraryType: known.has(id) ? 'group' : 'user'}),
      },
      Groups: {
        get: id => known.get(id), getAll: () => [...known.values()],
        getGroupIDFromLibraryID: id => id,
        getPermissionsFromJSON: dependencies.group_permissions,
      },
      Utilities: {
        arrayDiff: (a, b) => a.filter(value => !b.includes(value)),
        isEmpty: value => !value || !Object.keys(value).length,
      },
      Sync: { Data: { Local: {
        getSkippedLibraries: () => [], getSkippedGroups: () => [],
        checkLibraryForAccess: async () => true,
      }}},
      Prompt: { confirm() { throw new Error('Group-removal prompts need the desktop runtime'); } },
    };
    const client = {
      getGroupVersions: async () => fixtures.versions,
      getGroup: async id => {
        fetched.push(id);
        if (!fixtures.metadata[id]) throw new Error('No metadata fixture for group ' + id);
        return fixtures.metadata[id];
      },
    };
    const libraries = await selected(client, {}, fixtures.keyInfo, fixtures.libraries ?? []);
    return {
      libraries, fetched,
      groups: [...known.values()].map(group => ({
        id: group.id, version: group.version,
        editable: group.editable, filesEditable: group.filesEditable,
      })),
    };
  })()`;
}
