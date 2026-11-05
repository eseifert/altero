import { accessibilityProblems, expect, signIn, state, test } from './state'

const labels = {
  'en-US': {
    personal: 'Everything in your library on this server is deleted first, files included. Nothing is moved to the trash.',
    named: (name: string) => `Everything in ${name} is deleted first, files included. Nothing is moved to the trash.`,
    group: 'Everything in it is deleted: items, collections, tags and attachments. Nothing is moved to the trash.',
    delete: 'Delete', cancel: 'Cancel', deleted: 'Group deleted.',
  },
  'en-GB': {
    personal: 'Everything in your library on this server is deleted first, files included. Nothing is moved to the bin.',
    named: (name: string) => `Everything in ${name} is deleted first, files included. Nothing is moved to the bin.`,
    group: 'Everything in it is deleted: items, collections, tags and attachments. Nothing is moved to the bin.',
    delete: 'Delete', cancel: 'Cancel', deleted: 'Group deleted.',
  },
  ja: {
    personal: 'このサーバー上のライブラリの内容は、ファイルも含めて先にすべて削除されます。ごみ箱には移動しません。',
    named: (name: string) => `${name} の内容は、ファイルも含めて先にすべて削除されます。ごみ箱には移動しません。`,
    group: 'ライブラリ内のアイテム、コレクション、タグ、添付ファイルがすべて削除されます。ごみ箱には移動しません。',
    delete: '削除', cancel: 'キャンセル', deleted: 'グループを削除しました。',
  },
  'zh-CN': {
    personal: '你在此服务器上的文库内容会先被全部删除，包括文件。内容不会移入回收站。',
    named: (name: string) => `${name} 中的所有内容会先被删除，包括文件。内容不会移入回收站。`,
    group: '文库中的所有内容都会被删除：条目、分类、标签和附件。内容不会移入回收站。',
    delete: '删除', cancel: '取消', deleted: '群组已删除。',
  },
  'zh-TW': {
    personal: '你在此伺服器上的文獻庫內容會先被全部刪除，包括檔案。內容不會移至垃圾筒。',
    named: (name: string) => `${name} 中的所有內容會先被刪除，包括檔案。內容不會移至垃圾筒。`,
    group: '文獻庫中的所有內容都會被刪除：項目、文獻集、標籤和附件。內容不會移至垃圾筒。',
    delete: '刪除', cancel: '取消', deleted: '群組已刪除。',
  },
  de: {
    personal: 'Die eigene Bibliothek auf diesem Server wird zuerst vollständig gelöscht, einschließlich der Dateien. Nichts wird in den Papierkorb verschoben.',
    named: (name: string) => `Der gesamte Inhalt von ${name} wird zuerst gelöscht, einschließlich der Dateien. Nichts wird in den Papierkorb verschoben.`,
    group: 'Der gesamte Inhalt der Bibliothek wird gelöscht: Einträge, Sammlungen, Schlagwörter und Anhänge. Nichts wird in den Papierkorb verschoben.',
    delete: 'Löschen', cancel: 'Abbrechen', deleted: 'Gruppe gelöscht.',
  },
  es: {
    personal: 'Todo el contenido de su biblioteca en este servidor se elimina primero, archivos incluidos. Nada se mueve a la Papelera.',
    named: (name: string) => `Todo el contenido de ${name} se elimina primero, archivos incluidos. Nada se mueve a la Papelera.`,
    group: 'Todo el contenido de la biblioteca se elimina: ítems, colecciones, etiquetas y adjuntos. Nada se mueve a la Papelera.',
    delete: 'Eliminar', cancel: 'Cancelar', deleted: 'Grupo eliminado.',
  },
  gl: {
    personal: 'Primeiro elimínase todo o contido da túa biblioteca neste servidor, ficheiros incluídos. Nada se move ao Lixo.',
    named: (name: string) => `Primeiro elimínase todo o contido de ${name}, ficheiros incluídos. Nada se move ao Lixo.`,
    group: 'Todo o contido da biblioteca elimínase: elementos, coleccións, etiquetas e anexos. Nada se move ao Lixo.',
    delete: 'Eliminar', cancel: 'Cancelar', deleted: 'Grupo eliminado.',
  },
  eu: {
    personal: 'Hemengo zure liburutegiko guztia ezabatzen da lehenik, fitxategiak barne. Ez da ezer Zaborrera eramaten.',
    named: (name: string) => `${name} liburutegiko guztia ezabatzen da lehenik, fitxategiak barne. Ez da ezer Zaborrera eramaten.`,
    group: 'Liburutegiko eduki guztia ezabatzen da: elementuak, bildumak, etiketak eta eranskinak. Ez da ezer Zaborrera eramaten.',
    delete: 'Ezabatu', cancel: 'Utzi', deleted: 'Taldea ezabatu da.',
  },
  is: {
    personal: 'Öllu í færslusafninu þínu hér er eytt fyrst, skrám meðtöldum. Ekkert er fært í ruslið.',
    named: (name: string) => `Öllu í ${name} er eytt fyrst, skrám meðtöldum. Ekkert er fært í ruslið.`,
    group: 'Öllu í færslusafninu er eytt: færslum, söfnum, merkjum og viðhengjum. Ekkert er fært í ruslið.',
    delete: 'Eyða', cancel: 'Hætta við', deleted: 'Hópi eytt.',
  },
  pl: {
    personal: 'Wszystko w twojej tutejszej bibliotece zostaje najpierw usunięte, razem z plikami. Nic nie trafia do Kosza.',
    named: (name: string) => `Wszystko w ${name} zostaje najpierw usunięte, razem z plikami. Nic nie trafia do Kosza.`,
    group: 'Cała zawartość biblioteki zostaje usunięta: elementy, kolekcje, etykiety i załączniki. Nic nie trafia do Kosza.',
    delete: 'Usuń', cancel: 'Anuluj', deleted: 'Grupa została usunięta.',
  },
  ru: {
    personal: 'Всё содержимое вашей библиотеки на этом сервере сначала удаляется, включая файлы. Ничего не перемещается в Корзину.',
    named: (name: string) => `Всё содержимое ${name} сначала удаляется, включая файлы. Ничего не перемещается в Корзину.`,
    group: 'Всё содержимое библиотеки удаляется: записи, коллекции, теги и вложения. Ничего не перемещается в Корзину.',
    delete: 'Удалить', cancel: 'Отменить', deleted: 'Группа удалена.',
  },
  af: {
    personal: 'Die hele inhoud van u biblioteek op hierdie bediener word eers geskrap, lêers ingesluit, sonder om dit na die asblik te skuif.',
    named: (name: string) => `Die hele inhoud van ${name} word eers geskrap, lêers ingesluit, sonder om dit na die asblik te skuif.`,
    group: 'Alles in die biblioteek word geskrap: items, versamelings, etikette en aanhegsels. Niks word na die asblik geskuif nie.',
    delete: 'Skrap', cancel: 'Kanselleer', deleted: 'Groep geskrap.',
  },
  da: {
    personal: 'Alt i dit bibliotek på denne server slettes først, inklusive filer, uden at blive flyttet til papirkurven.',
    named: (name: string) => `Alt i ${name} slettes først, inklusive filer, uden at blive flyttet til papirkurven.`,
    group: 'Hele bibliotekets indhold slettes: elementer, samlinger, mærker og vedhæftede filer. Intet flyttes til papirkurven.',
    delete: 'Slet', cancel: 'Annullér', deleted: 'Gruppen er slettet.',
  },
  nb: {
    personal: 'Alt innholdet i biblioteket ditt på denne serveren slettes først, inkludert filer, uten å flyttes til søppelkorga.',
    named: (name: string) => `Alt innholdet i ${name} slettes først, inkludert filer, uten å flyttes til søppelkorga.`,
    group: 'Alt innholdet i biblioteket slettes: elementer, samlinger, emneord og vedlegg. Ingenting flyttes til søppelkorga.',
    delete: 'Slett', cancel: 'Avbryt', deleted: 'Gruppen er slettet.',
  },
  nl: {
    personal: 'De volledige inhoud van uw bibliotheek op deze server wordt eerst verwijderd, inclusief bestanden, zonder naar de prullenbak te worden verplaatst.',
    named: (name: string) => `De volledige inhoud van ${name} wordt eerst verwijderd, inclusief bestanden, zonder naar de prullenbak te worden verplaatst.`,
    group: 'De volledige inhoud van de bibliotheek wordt verwijderd: items, verzamelingen, labels en bijlagen. Er wordt niets naar de prullenbak verplaatst.',
    delete: 'Verwijderen', cancel: 'Annuleren', deleted: 'Groep verwijderd.',
  },
  nn: {
    personal: 'Alt innhaldet i biblioteket ditt på denne tenaren blir sletta først, filer medrekna, utan å bli flytta til søppelkorga.',
    named: (name: string) => `Alt innhaldet i ${name} blir sletta først, filer medrekna, utan å bli flytta til søppelkorga.`,
    group: 'Alt innhaldet i biblioteket blir sletta: element, samlingar, taggar og vedlegg. Ingenting blir flytta til søppelkorga.',
    delete: 'Slett', cancel: 'Avbryt', deleted: 'Gruppa er sletta.',
  },
  sv: {
    personal: 'Hela innehållet i ditt bibliotek på den här servern raderas först, även filerna, utan att flyttas till papperskorgen.',
    named: (name: string) => `Allt innehåll i ${name} raderas först, även filerna, utan att flyttas till papperskorgen.`,
    group: 'Hela bibliotekets innehåll raderas: källor, samlingar, etiketter och bilagor. Inget flyttas till papperskorgen.',
    delete: 'Radera', cancel: 'Avbryt', deleted: 'Gruppen har raderats.',
  },
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
