import { accessibilityProblems, expect, openItem, signIn, state, test } from './state'

for (const [tag, given, family] of [
  ['bg', 'име', 'фамилия'],
  ['ca', 'nom', 'cognom'],
  ['el', 'όνομα', 'επώνυμο'],
  ['fi', 'etunimi', 'sukunimi'],
  ['ha', 'suna na farko', 'sunan iyali'],
  ['id', 'nama depan', 'nama belakang'],
  ['is', 'eiginnafn', 'eftirnafn'],
  ['pt-BR', 'nome', 'sobrenome'],
  ['pt-PT', 'nome próprio', 'apelido'],
  ['sk', 'krstné meno', 'priezvisko'],
  ['sw', 'jina la kwanza', 'jina la ukoo'],
  ['ta', 'முதல் பெயர்', 'குடும்பப் பெயர்'],
  ['th', 'ชื่อ', 'นามสกุล'],
  ['tr', 'ad', 'soyadı'],
  ['yo', 'orúkọ àbísọ', 'orúkọ ìdílé'],
] as const) {
  test.describe(`creator names in ${tag}`, () => {
    test.use({ locale: tag })

    test('edits given and family names through their localized labels', async ({ page, request }, info) => {
      const title = `Creator labels ${tag} ${info.project.name}`
      const headers = { 'Zotero-API-Key': state().key }
      const created = await request.post('/users/1/items', {
        headers, data: [{ itemType: 'book', title,
          creators: [{ creatorType: 'author', firstName: 'Ada', lastName: 'Lovelace' }] }],
      })
      expect(created.ok()).toBe(true)
      const body = await created.json()
      expect(body.failed).toEqual({})
      const key = body.successful['0'].key as string
      const creators = async () => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data.creators

      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await openItem(page, title)
      const firstName = page.getByRole('textbox', { name: given, exact: true })
      const lastName = page.getByRole('textbox', { name: family, exact: true })
      await expect(firstName).toHaveValue('Ada')
      await expect(lastName).toHaveValue('Lovelace')
      await expect(firstName).toHaveAttribute('placeholder', given)
      await expect(lastName).toHaveAttribute('placeholder', family)
      await firstName.fill('Grace')
      await firstName.press('Enter')
      await expect.poll(creators).toEqual([{ creatorType: 'author', firstName: 'Grace', lastName: 'Lovelace' }])
      await lastName.fill('Hopper')
      await lastName.press('Enter')
      await expect.poll(creators).toEqual([{ creatorType: 'author', firstName: 'Grace', lastName: 'Hopper' }])
      await page.reload()
      await openItem(page, title)
      await expect(firstName).toHaveValue('Grace')
      await expect(lastName).toHaveValue('Hopper')
      await page.screenshot({ path: info.outputPath(`${tag}-creator.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
    })
  })
}
