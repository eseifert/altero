import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useLibraryStore, type ItemEnvelope } from './library'
import { useUploadStore } from './uploads'

const { requestMock, uploadMock } = vi.hoisted(() => ({ requestMock: vi.fn(), uploadMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
  upload: uploadMock,
}))

const LIBRARY = {
  id: 1,
  type: 'user',
  ownerId: 1,
  name: 'Ada',
  version: 4,
  prefix: '/users/1',
  writable: true,
  permission: 'inherit',
  filesEditable: true,
  maxUploadBytes: 100,
}

function entry(key: string, data: Partial<ItemEnvelope['data']> = {}): ItemEnvelope {
  return { key, version: 5, data: { itemType: 'book', title: key, ...data }, meta: {} }
}

const BOOK = entry('BOOK2345')

let children: ItemEnvelope[] = []

beforeEach(() => {
  setActivePinia(createPinia())
  children = []
  requestMock.mockReset()
  uploadMock.mockReset()
  requestMock.mockImplementation((path: string) => {
    if (path === '/web/libraries') return Promise.resolve([LIBRARY])
    if (path.includes('/children')) return Promise.resolve({ items: children })
    if (path.includes('/collections')) return Promise.resolve({ collections: [] })
    if (path.includes('/tags')) return Promise.resolve({ tags: [] })
    if (path.includes('/items/')) return Promise.resolve(BOOK)
    return Promise.resolve({ total: 1, items: [BOOK] })
  })
  uploadMock.mockImplementation((path: string) =>
    Promise.resolve(entry('NEWW2345', { itemType: 'attachment', path })),
  )
})

async function opened() {
  const store = useLibraryStore()
  await store.loadLibraries()
  return store
}

function pdf(name = 'paper.pdf', size = 10): File {
  const file = new File(['x'.repeat(size)], name, { type: 'application/pdf', lastModified: 1793120000000 })
  return file
}

function sentTo(): URL[] {
  return uploadMock.mock.calls.map(([path]) => new URL(path as string, 'http://x'))
}

describe('uploading files', () => {
  it('attaches a file under an item, titled the desktop’s way', async () => {
    const store = await opened()

    await store.uploadFiles([pdf()], { parentItem: BOOK.key })

    const [url] = sentTo()
    expect(url!.pathname).toBe('/web/libraries/1/attachments')
    expect(Object.fromEntries(url!.searchParams)).toEqual({
      filename: 'paper.pdf',
      mtime: '1793120000000',
      title: 'PDF',
      parentItem: BOOK.key,
    })
  })

  it('leaves the title to the server for a second PDF', async () => {
    children = [entry('OLDD2345', { itemType: 'attachment', linkMode: 'imported_file', contentType: 'application/pdf' })]
    const store = await opened()

    await store.uploadFiles([pdf()], { parentItem: BOOK.key })

    expect(sentTo()[0]!.searchParams.has('title')).toBe(false)
  })

  it('files a file on its own into the collection named', async () => {
    const store = await opened()

    await store.uploadFiles([pdf()], { collection: 'COLL2345' })

    const params = sentTo()[0]!.searchParams
    expect(params.get('collections')).toBe('COLL2345')
    expect(params.has('parentItem')).toBe(false)
    expect(params.has('title')).toBe(false)
  })

  it('sends them one after another', async () => {
    const store = await opened()
    let inFlight = 0
    let most = 0
    uploadMock.mockImplementation(async () => {
      inFlight += 1
      most = Math.max(most, inFlight)
      await Promise.resolve()
      inFlight -= 1
      return entry('NEWW2345', { itemType: 'attachment' })
    })

    const made = await store.uploadFiles([pdf('a.pdf'), pdf('b.pdf')], {})

    expect(made).toHaveLength(2)
    expect(most).toBe(1)
  })

  it('does not send a file larger than the server takes, and says so', async () => {
    const store = await opened()

    const made = await store.uploadFiles([pdf('huge.pdf', 101), pdf('fine.pdf')], {})

    expect(sentTo().map((url) => url.searchParams.get('filename'))).toEqual(['fine.pdf'])
    expect(made).toHaveLength(1)
    const refused = useUploadStore().uploads
    expect(refused).toHaveLength(1)
    expect(refused[0]!.name).toBe('huge.pdf')
    expect(refused[0]!.error).toContain('100')
  })

  it('keeps going past a file that failed, which stays on the panel', async () => {
    const store = await opened()
    uploadMock
      .mockRejectedValueOnce(new ApiError('This group does not allow file uploads', 403))
      .mockResolvedValueOnce(entry('NEWW2345', { itemType: 'attachment' }))

    const made = await store.uploadFiles([pdf('a.pdf'), pdf('b.pdf')], {})

    expect(made).toHaveLength(1)
    expect(useUploadStore().uploads.map((upload) => upload.error)).toEqual([
      'This group does not allow file uploads',
    ])
  })

  it('reads the open item’s attachments again afterwards', async () => {
    const store = await opened()
    await store.select(BOOK)
    const added = entry('NEWW2345', { itemType: 'attachment', parentItem: BOOK.key })
    children = [added]

    await store.uploadFiles([pdf()], { parentItem: BOOK.key })

    expect(store.children.map((child) => child.key)).toEqual(['NEWW2345'])
  })
})

describe('replacing a file', () => {
  const ATTACHMENT = entry('ATTA2345', {
    itemType: 'attachment',
    linkMode: 'imported_file',
    md5: 'a'.repeat(32),
  })

  it('states the digest it replaces', async () => {
    const store = await opened()

    await store.replaceFile(ATTACHMENT, pdf('v2.pdf'))

    const [path, , options] = uploadMock.mock.calls[0]!
    expect(path).toBe('/web/libraries/1/items/ATTA2345/file?filename=v2.pdf&mtime=1793120000000')
    expect(options).toMatchObject({ method: 'PUT', headers: { 'If-Match': 'a'.repeat(32) } })
  })

  it('asks for no file at all where there is none', async () => {
    const store = await opened()

    await store.replaceFile({ ...ATTACHMENT, data: { ...ATTACHMENT.data, md5: undefined } }, pdf())

    expect(uploadMock.mock.calls[0]![2]).toMatchObject({ headers: { 'If-None-Match': '*' } })
  })

  it('shows the file that won when another replaced it first', async () => {
    const store = await opened()
    const newer = { ...ATTACHMENT, version: 9, data: { ...ATTACHMENT.data, md5: 'b'.repeat(32) } }
    await store.select(ATTACHMENT)
    uploadMock.mockRejectedValueOnce(new ApiError('If-Match set but file does not match', 412))
    requestMock.mockImplementation((path: string) =>
      Promise.resolve(path.endsWith('/items/ATTA2345') ? newer : { items: [] }),
    )

    expect(await store.replaceFile(ATTACHMENT, pdf())).toBeNull()

    expect(store.selected?.data.md5).toBe('b'.repeat(32))
    expect(useUploadStore().uploads[0]!.error).toBe(
      'The file was replaced elsewhere first. This is the new one.',
    )
  })
})

describe('a web link', () => {
  it('is made under its item with its address and title', async () => {
    const store = await opened()
    requestMock.mockImplementation((path: string, options?: { method?: string }) => {
      if (options?.method === 'POST') return Promise.resolve(entry('LINK2345', { itemType: 'attachment' }))
      if (path === '/web/libraries') return Promise.resolve([LIBRARY])
      return Promise.resolve({ total: 0, items: [], collections: [] })
    })

    await store.createItem('attachment', {
      parentItem: BOOK.key,
      link: { url: 'https://example.org/', title: 'Example' },
    })

    const posted = requestMock.mock.calls.find(([, options]) => options?.method === 'POST')!
    expect(posted[1].body).toEqual({
      itemType: 'attachment',
      linkMode: 'linked_url',
      url: 'https://example.org/',
      title: 'Example',
      parentItem: BOOK.key,
    })
  })
})
