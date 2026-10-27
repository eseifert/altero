import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/*
 * Files dragged in from the computer.
 *
 * Not `dragging.ts`, which carries rows within the page by pointer events: a
 * file from the operating system arrives only as the browser's own drag
 * events, and only those carry it. The targets are found the same way,
 * though -- by an attribute on the element under the pointer, `data-file-drop`
 * where a target means something only to files and `data-drop` where it is a
 * place rows are dropped too -- so a collection is one target whatever is
 * carried onto it.
 *
 * Listened for on the window, so that a file let go anywhere else is refused
 * rather than opened by the browser in place of the page, which is what it
 * does with a file dropped where nothing took it: a reader who missed the
 * collection by a few pixels would otherwise lose the library they had open.
 */

/** Whether a drag is carrying files, which is all this is about. */
export function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files')
}

/** The target under ``element``, named as the view names it. */
export function dropTarget(element: EventTarget | null): string | null {
  if (!(element instanceof Element)) return null
  const found = element.closest<HTMLElement>('[data-file-drop], [data-drop]')
  return found?.dataset.fileDrop ?? found?.dataset.drop ?? null
}

/**
 * The files a drop holds, without folders.
 *
 * A folder arrives as an entry with no type and no bytes the browser will
 * read, and an upload of it would fail half way; `webkitGetAsEntry` is the
 * one way to tell, and every browser this interface supports has it.
 */
export function droppedFiles(transfer: DataTransfer | null): { files: File[]; folders: number } {
  if (!transfer) return { files: [], folders: 0 }
  const files: File[] = []
  let folders = 0
  const items = Array.from(transfer.items ?? [])
  if (!items.length) return { files: Array.from(transfer.files), folders }
  for (const item of items) {
    if (item.kind !== 'file') continue
    if (item.webkitGetAsEntry?.()?.isDirectory) {
      folders += 1
      continue
    }
    const file = item.getAsFile()
    if (file) files.push(file)
  }
  return { files, folders }
}

export interface FileDrop {
  /** The target files would land on now, if it takes them. */
  target: Ref<string | null>
  /** Whether files are being dragged over the page at all. */
  active: Ref<boolean>
}

export function useFileDrop(options: {
  accepts: (target: string) => boolean
  onDrop: (target: string, files: File[], folders: number) => void
}): FileDrop {
  const target = ref<string | null>(null)
  const active = ref(false)
  /* Entering a child leaves its parent first, so the page counts its way in
     and out rather than believing the first `dragleave`. */
  let depth = 0

  function reset(): void {
    depth = 0
    target.value = null
    active.value = false
  }

  function enter(event: DragEvent): void {
    if (!carriesFiles(event)) return
    depth += 1
    active.value = true
  }

  function over(event: DragEvent): void {
    if (!carriesFiles(event)) return
    // Always taken, so the browser never opens the file in place of the page.
    event.preventDefault()
    const found = dropTarget(event.target)
    const accepted = found !== null && options.accepts(found) ? found : null
    target.value = accepted
    if (event.dataTransfer) event.dataTransfer.dropEffect = accepted ? 'copy' : 'none'
  }

  function leave(event: DragEvent): void {
    if (!carriesFiles(event)) return
    depth = Math.max(0, depth - 1)
    if (depth === 0) reset()
  }

  function drop(event: DragEvent): void {
    if (!carriesFiles(event)) return
    event.preventDefault()
    const found = dropTarget(event.target)
    reset()
    if (found === null || !options.accepts(found)) return
    const { files, folders } = droppedFiles(event.dataTransfer)
    if (files.length || folders) options.onDrop(found, files, folders)
  }

  onMounted(() => {
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
  })
  onBeforeUnmount(() => {
    window.removeEventListener('dragenter', enter)
    window.removeEventListener('dragover', over)
    window.removeEventListener('dragleave', leave)
    window.removeEventListener('drop', drop)
  })

  return { target, active }
}
