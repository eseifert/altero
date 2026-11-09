import { accessibilityProblems, expect, signIn, state, test } from './state'

const labels = {
  af: { duplicates: 'Duplikaatitems', merge: 'Voeg items saam', select: 'Kies', merged: 'Items saamgevoeg.' },
  bg: { duplicates: 'Дублирани записи', merge: 'Сливане на записите', select: 'Избиране', merged: 'Записите са слети.' },
  es: { duplicates: 'Elementos duplicados', merge: 'Fusionar elementos', select: 'Seleccionar', merged: 'Elementos fusionados.' },
  fi: {
    duplicates: 'Kaksoiskappaleet', merge: 'Yhdistä nimikkeet', select: 'Valitse', merged: 'Nimikkeet yhdistetty.',
    instruction: 'Valitse kentät, jotka säilytetään muista versioista:',
  },
  hr: { duplicates: 'Duplicirane stavke', merge: 'Spoji stavke', select: 'Odaberi', merged: 'Stavke su spojene.' },
  id: { duplicates: 'Item duplikat', merge: 'Gabungkan Item', select: 'Pilih', merged: 'Item digabungkan.' },
  km: { duplicates: 'ឯកសារត្រួត', merge: 'បញ្ចូលឯកសារចូលគ្នា', select: 'ជ្រើសរើស', merged: 'បានបញ្ចូលឯកសារចូលគ្នា។' },
  lv: {
    duplicates: 'Vienumu dublikāti', merge: 'Apvienot vienumus', select: 'Atlasīt',
    merged: 'Vienumi apvienoti.', master: 'Galvenais vienums',
    versionInstruction: 'Izvēlieties vienuma versiju, ko izmantot kā galveno vienumu:',
    instruction: 'Atlasiet laukus, kurus paturēt no citām vienuma versijām:',
    trashWarning: 'Pārējās versijas tiks pārvietotas uz miskasti.',
  },
  mn: { duplicates: 'Давхардсан зүйлс', merge: 'Зүйлсийг нэгтгэх', select: 'Сонгох', merged: 'Зүйлсийг нэгтгэлээ.' },
  ro: {
    duplicates: 'Înregistrări duplicate', merge: 'Unește înregistrările', select: 'Selectează',
    merged: 'Înregistrările au fost unite.', master: 'Înregistrare principală',
    versionInstruction: 'Alege versiunea înregistrării pe care o vei folosi ca înregistrare principală:',
  },
  sk: { duplicates: 'Duplicitné záznamy', merge: 'Zlúčiť záznamy', select: 'Vybrať', merged: 'Záznamy boli zlúčené.', master: 'Hlavný záznam' },
  sl: { duplicates: 'Podvojeni vnosi', merge: 'Spoji vnose', select: 'Izberi', merged: 'Vnosi so spojeni.', master: 'Glavni vnos' },
  sv: { duplicates: 'Källdubbletter', merge: 'Sammanfoga källor', select: 'Markera', merged: 'Källor sammanfogade.', master: 'Huvudkälla' },
  th: { duplicates: 'รายการซ้ำ', merge: 'รวมรายการ', select: 'เลือก', merged: 'รวมรายการแล้ว' },
  tr: {
    duplicates: 'Yinelenmiş Eserler', merge: 'Eserleri Birleştir', select: 'Seç',
    merged: 'Eserler birleştirildi.', master: 'Asıl eser',
    versionInstruction: 'Eserin hangi versiyonunun asıl eser olarak kullanılacağını seçiniz:',
    instruction: 'Eserin diğer versiyonlarından hangi alanların tutulacağını seçiniz:',
  },
  uk: {
    duplicates: 'Дублікати документів', merge: "Об'єднати документи", select: 'Виділити',
    merged: 'Документи об’єднано.', master: 'Основний документ',
    versionInstruction: 'Виберіть версію документа, яку слід використати як основний документ:',
    instruction: 'Виберіть поля для збереження з інших версій документа:',
  },
  vi: { duplicates: 'Các mục trùng lặp', merge: 'Gộp các mục', select: 'Chọn', merged: 'Đã gộp các mục.' },
}

for (const [tag, translated] of Object.entries(labels)) {
  test.describe(`localized merge ${tag}`, () => {
    test.use({ locale: tag })

    test('reviews type warnings and field choices before merging', async ({ page, request }, info) => {
      const title = `Localized merge ${tag} ${info.project.name}`
      const headers = { 'Zotero-API-Key': state().key }
      const response = await request.post('/users/1/items', { headers, data: [
        { itemType: 'book', title, publisher: 'Original publisher', dateAdded: '2020-01-01T00:00:00Z' },
        { itemType: 'book', title, publisher: 'Chosen publisher', dateAdded: '2021-01-01T00:00:00Z' },
        { itemType: 'journalArticle', title, dateAdded: '2022-01-01T00:00:00Z' },
      ] })
      expect(response.ok()).toBe(true)
      const body = await response.json()
      expect(body.failed).toEqual({})
      const [master, duplicate, differentType] = ['0', '1', '2'].map(index => body.successful[index].key as string)
      await signIn(page)
      await expect(page.locator('html')).toHaveAttribute('lang', tag)
      await page.locator('.library__scope').filter({ hasText: translated.duplicates }).click()
      if ('master' in translated) {
        await expect(page.locator(`.duplicate-group__row[data-row="${master}"] .duplicate-group__master`)).toHaveText(translated.master)
      }
      await page.locator(`.duplicate-group__row[data-row="${master}"]`).click()
      const pane = page.locator('.merge-pane')
      await expect(pane.getByRole('heading')).toHaveText(translated.merge)
      const warning = pane.locator('select[name="merge-master"] + p')
      await expect(warning).toBeVisible()
      await expect(warning).not.toHaveText('Merged items must all be of the same item type.')
      await expect(pane.locator('[data-merge-review]')).toBeDisabled()
      await pane.getByRole('button', { name: translated.select, exact: true }).click()
      await pane.locator(`input[type=checkbox][value="${differentType}"]`).uncheck()
      await expect(pane.locator('.merge-pane__master')).toBeVisible()
      await expect(pane.locator('.merge-pane__master')).not.toHaveText(
        'Choose the version of the item to use as the master item:',
      )
      if ('versionInstruction' in translated) {
        await expect(pane.locator('.merge-pane__master')).toHaveText(translated.versionInstruction)
      }
      await expect(pane.locator('.merge-pane__instruction')).toBeVisible()
      await expect(pane.locator('.merge-pane__instruction')).not.toHaveText(
        'Select fields to keep from other versions of the item:',
      )
      if ('instruction' in translated) {
        await expect(pane.locator('.merge-pane__instruction')).toHaveText(translated.instruction)
      }
      await pane.locator('select[name="merge-publisher"]').selectOption('1')
      await pane.locator('[data-merge-review]').click()
      await expect(pane.locator('[data-merge-confirm]')).toHaveText(translated.merge)
      if ('trashWarning' in translated) {
        await expect(pane.getByText(translated.trashWarning, { exact: true })).toBeVisible()
      }
      await page.screenshot({ path: info.outputPath(`${tag}-merge.png`), fullPage: true })
      expect(await accessibilityProblems(page)).toEqual([])
      await pane.locator('[data-merge-confirm]').click()
      await expect(page.getByText(translated.merged, { exact: true })).toBeVisible()
      const get = async (key: string) => (await (await request.get(`/users/1/items/${key}`, { headers })).json()).data
      expect((await get(master!)).publisher).toBe('Chosen publisher')
      expect((await get(duplicate!)).deleted).toBe(1)
      expect((await get(differentType!)).deleted ?? 0).toBe(0)
    })
  })
}
