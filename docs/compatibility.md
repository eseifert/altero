# Compatibility notes

altero targets the Zotero desktop application, so where the published
documentation and the official [dataserver](https://github.com/zotero/dataserver)
disagree, the dataserver wins — even when its behaviour looks like a bug. Every
such case is listed here, with the source that settles it.

Two sources are used throughout:

- the live API at `https://api.zotero.org`, compared response by response
- the reference implementation, chiefly `model/API.inc.php`,
  `model/Tags.inc.php` and `model/Items.inc.php`

## Search syntax

`Zotero_API::getSearchParamValues` (`model/API.inc.php`) is the authority for
the `itemType` and `tag` parameters, and it differs from the prose documentation
in two ways that change results.

**Negation covers the whole value.** The leading `-` is stripped before the
value is split on `||`, so `itemType=-book || journalArticle` excludes items of
*either* type. It does not mean "not a book, or a journal article". The
documentation's wording suggests per-alternative negation; the implementation
has none.

**`||` only separates when surrounded by whitespace.** The split is
`preg_split("/\s+\|\|\s+/", $val)`. `tag=a||b` is therefore a single tag
literally named `a||b`, and `tag=a ||b` likewise does not split. This is what
lets a tag containing a bare `||` round-trip. Every example in the documentation
uses the spaced form, so clients are unaffected.

A leading hyphen is escaped as `\-`, and only the whole value is stripped —
once, before parsing — so inner spacing in `tag=foo bar || bar` survives.

## Pagination of the sync formats

`Zotero_API::getLimitMax` returns `0` for `format=keys` and `format=versions`,
and their default limit is `0` as well. Zero means *no limit*: both formats
return the entire result set in one response and carry no `Link` header.

This matters more than it looks. The desktop application reads the whole of
`format=versions` to decide what to sync; truncating it to the usual 25 would
not produce an error, it would silently make the client believe the library
contains 25 objects. An explicit `limit` is still honoured for these formats,
and is not capped at 100.

For every other format the maximum stays 100 and the default 25.

## Parameter handling

| Behaviour | Source |
| --- | --- |
| `limit=0` or a negative limit falls back to the default, rather than erroring or clamping to 1 | `parseQueryParams`, `case 'limit'` |
| A limit above the maximum is clamped, not rejected | same |
| `sort=asc` / `sort=desc` is moved to `direction`, keeping the default sort | `parseQueryParams`, `case 'sort'` |
| `qmode` is compared lowercased, so `startsWith` and `startswith` both work | `parseQueryParams`, `case 'qmode'` |
| Any sort field whose name begins with `date` defaults to descending; everything else ascending | `getDefaultDirection` |
| `itemType` may not be repeated | `Zotero_Items::search` |
| `numItems` is a valid sort only for tag endpoints | `parseQueryParams`, `case 'sort'` |
| `extra` and `serverDateModified` are valid item sort fields | same |

## Item type schema

These came out of comparing all 163 schema responses against the live API.

**`/itemTypes` and `/itemFields` are ordered by localized name**, not by
identifier, so the order changes with `locale`. Sorting is by code point, which
is why `Software` (`computerProgram`) sorts under S and `TV Broadcast` precedes
`Thesis`.

**`/itemTypeCreatorTypes` pins the primary type first** and sorts the remainder
by localized name — again per locale, so the German ordering differs from the
English one.

**`/itemFields` omits base-only fields.** Names such as `medium` and `authority`
appear only as the `baseField` of another field and are not listed, though they
remain valid in writes.

**Templates disagree with the schema for two item types.** The schema marks
`creator` as the primary creator type for `videoRecording` and `radioBroadcast`,
and `/itemTypeCreatorTypes` reports it as such, yet `/items/new` seeds those
templates with `director`. Both behaviours are reproduced, so a template fetched
from altero is interchangeable with one fetched from Zotero. See
`TEMPLATE_CREATOR_TYPES` in `altero/itemschema/registry.py`.

## Deliberate differences

Two places where altero does not copy upstream, both improvements rather than
divergences a client can notice:

- **An unknown `locale` falls back to `en-US`.** The live API answers `500`.
- **Fields sharing a localized name may order differently.** Three fields are
  called "Format"; upstream breaks the tie on an internal identifier that the
  published schema does not contain, so their relative order is arbitrary here.

## Unverified

- The tag JSON envelope carries a top-level `version`. `Zotero_Tag::toJSON`
  returns only `tag` and `type`, and the envelope is assembled elsewhere in the
  controller; this has not been confirmed against a live response, since it
  needs a readable library. Harmless if wrong — clients read tag versions from
  `format=versions` — but worth checking.
