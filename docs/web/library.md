# Browsing and organizing a library

Choose **My Library** or a group in the sidebar. Select a collection or view on
the left, an item in the middle, and use its details on the right. Browser
changes synchronize with Zotero Desktop.

## Browsing a library

Select the library name to show its top-level items. Expand collections with
their arrows. **Recently Read**, **Duplicate Items**, **Unfiled Items** and
**Trash** offer other ways to find records. **My Publications** appears only
in your personal library.

Use search to find references and tags to narrow the list. Selecting several
tags requires all of them. Use **Show more** to load more items.
Drag the dividers to resize the panes; your browser remembers their widths.

Open a child note or attachment from its parent. **Close details** returns to
that parent. Attachments can be opened or downloaded. The citation section
renders a reference in the style you choose.

## Editing an item

- **Create:** press **+** above the list and choose an item type. The new item goes into the current collection.
- **Edit fields:** select a value, type, then press Enter or leave the field to save. Escape cancels. Use Shift+Enter to save multi-line fields such as Abstract and Extra.
- **Change type:** use the type menu. Review the warning if the new type cannot hold some fields.
- **Edit creators:** choose a role and enter names. **More Options…** switches to a single name for an organization and offers reordering; the grip can also be dragged.
- **Edit tags:** use **+** under **Tags**, the pencil to rename one on this item, or **×** to remove it from this item.
- **Relate items:** use **+** under **Related**, search, and select a result. **−** removes the relationship from both items.
- **Set rights:** use the license chooser beside **Rights**, or enter other rights text.

An item in Trash must be restored before editing. In a read-only library,
editing controls are unavailable.

Changes made elsewhere appear while the page is open. If someone changes the
same field while you are editing, review the local and remote values and
choose which to keep. Tags are applied on top of current tags.

## Writing a note

Use the note button above the list to create a **New Standalone Note** or a
**New Item Note**. **+** beside an item's **Notes** adds a child note.

Select text for formatting tools. On a phone or tablet, the tools sit above
the keyboard. Type `/` at the start of a line or after a space to choose a
block type. Common shortcuts and Markdown-style headings and lists also work.
The full-screen button gives you more room to write.

Notes save after you stop typing; **Saved.** confirms completion. If the note
changed elsewhere, choose between the local and remote versions.

Existing Zotero citations, annotations and embedded images are preserved but
cannot be added here. Math appears as TeX source. Notes in an unsupported
newer format open read-only.

## Adding files and links

| Task | Action |
| --- | --- |
| Attach a file to an item | **Attach File…**, **+** beside **Attachments**, or drop a file onto the item |
| Add a standalone file | **Add File…**, or drop a file onto the library, collection or item list |
| Attach a web address | **Attach Web Link…** and enter the URL |
| Rename a file | Edit **Filename** in the attachment details |
| Replace its contents | **Replace File…** in the attachment details |

Uploads show progress and a cancel button. Add individual files; folders cannot
be dropped. The default file limit is 1 GiB, but your administrator may set a
different limit. Group policy may prevent file uploads.

Renaming a file keeps its title. Replacing it keeps the attachment record and
title but uses the new file's name. If another person replaced the file while
yours was uploading, reload before trying again.

## Collections

Use **+** on a library row to create a top-level collection, or on a collection
to create a subcollection. Open a collection's settings to rename, move or
delete it. You can also drag it onto another collection or the library row.

Deleting a collection leaves its items in the library and promotes its
subcollections. It does not delete the references or files.

To give others a read-only link, open **Share a link…** in the collection settings.
See [Sharing one collection](sharing.md#sharing-one-collection).

## Items

Use **Move or copy…**, **Move to trash**, **Restore** or **Delete** in the
detail pane. For several items, select them first; the pane then offers actions
for the selection.

### Selecting items

- Ctrl-click, or Cmd-click on a Mac, adds or removes a row.
- Shift-click selects a range.
- Ctrl/Cmd-A selects the loaded page, or the active duplicate group.
- **Select** shows checkboxes for touch and keyboard use.

Arrow keys move through the list. Enter opens the details; F2 edits the title.
Press `?` for the full shortcut list.

### Moving and copying

| Drop target | Result |
| --- | --- |
| A collection in the same library | Add membership; keep existing memberships |
| A collection while holding Shift | Move from the current collection to the target |
| The current library row | Remove from the current collection |
| Another library | Copy the item, notes, attachments and tags; keep the original |
| Trash | Move the item to Trash |

A drag starting on a selected row carries the selection. Starting on another
row carries only that item. **Move or copy…** provides the same operations
without dragging, including the option to remove items from the current collection.

### Trash and undo

**Delete** on the keyboard moves an item to Trash. In Trash, it asks to delete
permanently. **Empty Trash** removes all trashed items after confirmation.
Permanent deletion cannot be undone.

To trash a child note or attachment, open its details from the parent. To
recover it later, select it in Trash and choose **Restore**. Restoring a child
does not restore its parent.

After filing, trashing, restoring, copying or merging, **Undo** appears briefly
in the confirmation message. A later change to the library can make undo
unavailable. If the message is gone, trashed items can still be restored from
Trash. Undoing a copy moves the new copies to the destination's Trash.

## Merging duplicates

1. Open **Duplicate Items** and select a group. Check that the records describe the same work.
2. Choose the master record; the oldest is selected by default.
3. Choose the field values and creator list to keep. Use **Select** to exclude a record that does not belong.
4. Press **Merge Items**, review the warning and confirm.

Merging needs at least two items of the same type and permission to edit and
remove them. It combines collections, tags, related items and children, then
moves the other records to Trash. Matching attachments may be combined;
files with notes are kept separately where needed for safe Zotero synchronization.

Use **Undo** in the confirmation message to reverse a merge while it is still
available. Restoring an individual duplicate from Trash later does not reverse
the merged fields or move children back. If the library changed during review,
reload and check the records again.

## Writing items out

Choose **Export…** above the list or in the detail or selection pane. Select
the current selection, filtered view or whole library, then an export format.
Export includes all matching references, beyond the loaded page.

Formats include BibTeX, BibLaTeX, CSL JSON, RIS, CSV and the other supported
Zotero export formats. These files contain references, without attachment
bytes or standalone notes and annotations. For complete backups, use a
[library archive](data-transfer.md#import-and-export).

## By touch

Tap **Select** to work with several items using checkboxes. Hold a row briefly
before dragging; moving immediately scrolls instead. Accepted destinations
are highlighted. Use **Move or copy…** for operations that otherwise require
keyboard modifiers.

## Tags

Selecting a sidebar tag filters the list. Its pencil renames it **throughout
the library**, including items outside the current view. Renaming onto an
existing name combines the tags. This has no undo.

For a change to just one item, edit tags in that item's details instead.
