// Fixtures replace persistence and HTTP, while original functions make decisions.
export function adapterScript(name) {
  if (name === "pure") return "selected(...args)";
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
