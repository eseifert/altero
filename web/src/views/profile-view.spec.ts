import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { i18n } from '@/i18n'
import { useAuthStore } from '@/stores/auth'

import ProfileView from './ProfileView.vue'

const { requestMock } = vi.hoisted(() => ({ requestMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  request: requestMock,
}))

const CC_BY = 'Creative Commons Attribution 4.0 International License'

function book(overrides: Record<string, unknown> = {}) {
  return {
    key: 'PUBLIC01',
    version: 3,
    data: {
      itemType: 'book',
      title: 'Notes on the Analytical Engine',
      date: '1843',
      creators: [{ creatorType: 'author', firstName: 'Ada', lastName: 'Lovelace' }],
      ...overrides,
    },
    meta: { creatorSummary: 'Lovelace' },
  }
}

const PROFILE = {
  username: 'ada',
  displayName: 'Ada Lovelace',
  numPublications: 1,
  owner: false,
  visibility: null,
}

/** Answer the page's requests, with `profile` and `items` as given. */
function serve(profile: unknown = PROFILE, items: unknown[] = [book()], total = items.length) {
  requestMock.mockImplementation((path: string) => {
    if (path.includes('/children')) return Promise.resolve({ total: 0, items: [] })
    if (path.includes('/items')) return Promise.resolve({ total, items })
    if (path.startsWith('/web/profiles/')) return Promise.resolve(profile)
    return Promise.resolve({})
  })
}

async function screen(username = 'ada') {
  const wrapper = mount(ProfileView, {
    props: { username },
    global: { plugins: [i18n], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flush()
  return wrapper
}

async function flush(): Promise<void> {
  for (let round = 0; round < 6; round += 1) {
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  i18n.global.locale.value = 'en-US'
  requestMock.mockReset()
})

describe('a profile page', () => {
  it('is headed by the name the person goes by', async () => {
    serve()

    const wrapper = await screen()

    expect(wrapper.text()).toContain('Ada Lovelace')
    expect(wrapper.text()).toContain('1 publication')
  })

  it('lists the published work with its author and date', async () => {
    serve()

    const wrapper = await screen()

    expect(wrapper.text()).toContain('Notes on the Analytical Engine')
    expect(wrapper.text()).toContain('Ada Lovelace')
    expect(wrapper.text()).toContain('1843')
  })

  it('says so when nothing has been published', async () => {
    serve({ ...PROFILE, numPublications: 0 }, [])

    const wrapper = await screen()

    expect(wrapper.text()).toContain('Nothing has been published here yet.')
  })

  it('opens one entry and asks for what was published with it', async () => {
    serve()
    const wrapper = await screen()

    await wrapper.find('.publication__summary').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/profiles/ada/items/PUBLIC01/children')
  })

  it('shows the files that came along, and a way to save them', async () => {
    requestMock.mockImplementation((path: string) => {
      if (path.includes('/children')) {
        return Promise.resolve({
          total: 1,
          items: [
            {
              key: 'FILE0001',
              version: 3,
              data: {
                itemType: 'attachment',
                linkMode: 'imported_file',
                title: 'The paper',
                filename: 'paper.pdf',
              },
              meta: {},
            },
          ],
        })
      }
      if (path.includes('/items')) return Promise.resolve({ total: 1, items: [book()] })
      return Promise.resolve(PROFILE)
    })
    const wrapper = await screen()

    await wrapper.find('.publication__summary').trigger('click')
    await flush()

    const links = wrapper.findAll('.publication__files a').map((link) => link.attributes('href'))
    expect(links).toContain('/web/profiles/ada/items/FILE0001/file')
    expect(links).toContain('/web/profiles/ada/items/FILE0001/file?download=true')
  })

  it('links a licence the publishing wizard offers to the licence itself', async () => {
    /* What the wizard's licence question was for: a reader has to be able to
       reach the terms, not merely read their name. */
    serve(PROFILE, [book({ rights: CC_BY })])
    const wrapper = await screen()

    await wrapper.find('.publication__summary').trigger('click')
    await flush()

    const link = wrapper.find('.publication__rights a')
    expect(link.attributes('href')).toBe('https://creativecommons.org/licenses/by/4.0/')
  })

  it('shows a rights statement that is not a known licence as the text it is', async () => {
    /* Guessing a URL for it would be inventing a permission nobody granted. */
    serve(PROFILE, [book({ rights: 'Ask me first' })])
    const wrapper = await screen()

    await wrapper.find('.publication__summary').trigger('click')
    await flush()

    expect(wrapper.find('.publication__rights').text()).toContain('Ask me first')
    expect(wrapper.find('.publication__rights a').exists()).toBe(false)
  })

  it('asks for the next page rather than the first one again', async () => {
    serve(PROFILE, [book()], 40)
    const wrapper = await screen()
    requestMock.mockClear()

    await wrapper.find('.profile__more').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/profiles/ada/items?limit=25&start=1')
  })

  it('reports a profile it may not read as one that is not there', async () => {
    /* The server does not distinguish the two, so neither can this. */
    requestMock.mockRejectedValue(new ApiError('No such profile', 404))

    const wrapper = await screen('grace')

    expect(wrapper.text()).toContain('No such profile')
  })

  it('mentions signing in to a visitor who is not, and to nobody else', async () => {
    requestMock.mockRejectedValue(new ApiError('No such profile', 404))

    const wrapper = await screen('grace')

    expect(wrapper.text()).toContain('Some profiles are shown only to people signed in.')
  })

  it('does not mention it to somebody already signed in', async () => {
    requestMock.mockRejectedValue(new ApiError('No such profile', 404))
    const wrapper = await screen('grace')
    useAuthStore().user = {
      id: 1,
      username: 'ada',
      displayName: 'Ada',
      email: null,
      emailVerified: false,
      language: null,
      timeZone: null,
      profileVisibility: 'public',
      administrator: false,
    }
    await flush()

    expect(wrapper.text()).not.toContain('Some profiles are shown only to people signed in.')
  })

  it('tells the owner who can see the page, and offers to change it', async () => {
    serve({ ...PROFILE, owner: true, visibility: 'users' })

    const wrapper = await screen()

    expect(wrapper.text()).toContain('This is your public page.')
    expect(wrapper.text()).toContain('Only people signed in to this server can see this page.')
    expect(wrapper.text()).toContain('Change who can see it')
  })

  it('tells nobody else any of that', async () => {
    /* `visibility` is sent to the owner alone; the page must not invent one. */
    serve()

    const wrapper = await screen()

    expect(wrapper.text()).not.toContain('This is your public page.')
  })

  it('loads the other person when the name in the address changes', async () => {
    serve()
    const wrapper = await screen()
    requestMock.mockClear()

    await wrapper.setProps({ username: 'grace' })
    await flush()

    expect(requestMock).toHaveBeenCalledWith('/web/profiles/grace')
  })
})

describe('citing something from a profile', () => {
  it('renders it with the server, in the style that was chosen', async () => {
    /* One CSL implementation, on the server, whichever page asked. */
    serve()
    const wrapper = await screen()
    await wrapper.find('.publication__summary').trigger('click')
    await flush()
    requestMock.mockResolvedValue({ bib: '<div>Lovelace, A. 1843.</div>' })

    await wrapper.find('.publication__select').setValue('apa')
    await wrapper.find('.publication__cite button').trigger('click')
    await flush()

    expect(requestMock).toHaveBeenCalledWith(
      '/web/profiles/ada/items/PUBLIC01/citation?style=apa',
    )
    expect(wrapper.find('.publication__bib').text()).toContain('Lovelace')
  })
})

describe('when the server does not answer', () => {
  it('says so rather than leaving the page blank', async () => {
    /* A refusal is reported as absence; a stopped server is neither, and used
       to render nothing at all. */
    requestMock.mockRejectedValue(new ApiError('Could not reach the server', 0))

    const wrapper = await screen()

    expect(wrapper.text()).toContain('Could not reach the server')
  })
})
