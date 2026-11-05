import { accessibilityProblems, expect, signIn, state, test } from './state'

const labels = {
  fr: {
    personal: 'Tout le contenu de votre bibliothèque sur ce serveur est d’abord supprimé, fichiers compris, sans passer par la corbeille.',
    named: (name: string) => `Tout le contenu de ${name} est d’abord supprimé, fichiers compris, sans passer par la corbeille.`,
    group: 'Tout son contenu est supprimé avec lui : documents, collections, marqueurs et pièces jointes. Rien n’est placé dans la corbeille.',
    delete: 'Supprimer', cancel: 'Annuler', deleted: 'Groupe supprimé.',
  },
  it: {
    personal: 'Tutto il contenuto della tua biblioteca su questo server viene prima eliminato, file compresi, senza passare dal cestino.',
    named: (name: string) => `Tutto il contenuto di ${name} viene prima eliminato, file compresi, senza passare dal cestino.`,
    group: 'Vengono eliminati anche tutti gli elementi, le collezioni, i tag e gli allegati della biblioteca. Nulla viene spostato nel cestino.',
    delete: 'Elimina', cancel: 'Annulla', deleted: 'Gruppo eliminato.',
  },
  'pt-BR': {
    personal: 'Todo o conteúdo da sua biblioteca neste servidor é excluído primeiro, incluindo os arquivos, sem passar pela lixeira.',
    named: (name: string) => `Todo o conteúdo de ${name} é excluído primeiro, incluindo os arquivos, sem passar pela lixeira.`,
    group: 'Todo o conteúdo da biblioteca é excluído: itens, coleções, etiquetas e anexos. Nada é enviado para a lixeira.',
    delete: 'Excluir', cancel: 'Cancelar', deleted: 'Grupo excluído.',
  },
  'pt-PT': {
    personal: 'Todo o conteúdo da sua biblioteca neste servidor é eliminado primeiro, incluindo os ficheiros, sem passar pelo lixo.',
    named: (name: string) => `Todo o conteúdo de ${name} é eliminado primeiro, incluindo os ficheiros, sem passar pelo lixo.`,
    group: 'Todo o conteúdo da biblioteca é eliminado: itens, coleções, etiquetas e anexos. Nada é enviado para o lixo.',
    delete: 'Eliminar', cancel: 'Cancelar', deleted: 'Grupo eliminado.',
  },
}

for (const [tag, translated] of Object.entries(labels)) {
  test.describe(`deletion warnings in ${tag}`, () => {
    test.use({ locale: tag })

    test('explains that replacement and group deletion bypass Trash', async ({ page, request }, info) => {
      const name = `Deletion warnings ${tag} ${info.project.name}`
      const headers = { 'Zotero-API-Key': state().key }
      const created = await request.post('/groups', { headers, data: { name } })
      expect(created.ok()).toBe(true)
      const group = await created.json()
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      const libraries = await (await page.request.get('/web/libraries')).json()
      const library = libraries.find((entry: { type: string; ownerId: number }) => entry.type === 'group' && entry.ownerId === group.id)
      const csrf = (await page.context().cookies()).find(cookie => cookie.name === 'altero_csrf')!.value
      const made = await page.request.post(`/web/libraries/${library.id}/items`, {
        headers: { 'X-CSRF-Token': decodeURIComponent(csrf) }, data: { itemType: 'book' },
      })
      expect(made.status()).toBe(201)
      const { key } = await made.json()
      const item = async () => (await (await page.request.get(`/web/libraries/${library.id}/items/${key}`)).json())
      const original = await item()
      await page.goto('/app/settings/migrate')
      await page.getByRole('checkbox').check()
      await expect(page.locator('.card__warning')).toHaveText(translated.personal)
      expect(await accessibilityProblems(page)).toEqual([])

      expect((await page.request.get(`/web/libraries/${library.id}/items`)).status()).toBe(200)
      await page.goto('/app/settings/import-export')
      await page.getByRole('combobox').selectOption(String(library.id))
      await page.getByRole('checkbox').check()
      await expect(page.locator('.card__warning')).toHaveText(translated.named(name))
      await page.screenshot({ path: info.outputPath(`${tag}-replacement.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      expect(await item()).toEqual(original)

      await page.goto('/app/groups')
      await page.locator('.groups__list button').filter({ hasText: name }).click()
      await expect(page.getByText(translated.group, { exact: true })).toBeVisible()
      await page.getByRole('button', { name: translated.delete, exact: true }).click()
      const confirmation = page.locator('[role=alert]')
      await expect(confirmation).toContainText(name)
      await confirmation.getByRole('button', { name: translated.cancel, exact: true }).click()
      expect(await item()).toEqual(original)
      await page.getByRole('button', { name: translated.delete, exact: true }).click()
      await page.screenshot({ path: info.outputPath(`${tag}-delete-group.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      await confirmation.getByRole('button', { name: translated.delete, exact: true }).click()
      await expect(page.locator('.groups__notice')).toHaveText(translated.deleted)
      expect((await request.get(`/groups/${group.id}`, { headers })).status()).toBe(404)
      expect((await page.request.get(`/web/libraries/${library.id}/items`)).status()).toBe(404)
    })
  })
}
