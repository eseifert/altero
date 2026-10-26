import { describe, expect, it } from 'vitest'

import { cleanBibliography, cleanNote } from './sanitize'

describe('cleaning a note', () => {
  it.each([
    ['an image handler', '<p>Hi</p><img src="x" onerror="alert(1)">', /onerror/i],
    ['a script', '<p>Hi</p><script>alert(1)</script>', /<script/i],
    ['a javascript: link', '<a href="javascript:alert(1)">go</a>', /javascript:/i],
    ['a script inside SVG', '<svg><script>alert(1)</script></svg>', /<script|<svg/i],
    ['a frame', '<iframe src="https://example.org"></iframe>', /<iframe/i],
    ['a form', '<form action="https://example.org"><input name="password"></form>', /<form|<input/i],
    ['a stylesheet', '<style>body { display: none }</style><p>Hi</p>', /<style/i],
    ['a background image', '<p style="background-image: url(https://example.org/x)">Hi</p>', /url\(/i],
    ['a covering overlay', '<div style="position: fixed; inset: 0">Hi</div>', /position|inset/i],
  ])('drops %s', (_, html, forbidden) => {
    expect(cleanNote(html)).not.toMatch(forbidden)
  })

  it('keeps what the note editor writes', () => {
    const html =
      '<div data-schema-version="9"><h1>Title</h1><p><strong>bold</strong> <em>it</em></p>' +
      '<p><span class="highlight" data-annotation="%7B%7D">quoted</span> ' +
      '<span class="citation" data-citation="%7B%7D">(Doe, 2019)</span></p>' +
      '<p style="text-align: center"><span style="color: #ff2020">red</span></p>' +
      '<ul><li>one</li></ul><table><tbody><tr><td>cell</td></tr></tbody></table></div>'

    const cleaned = cleanNote(html)

    expect(cleaned).toContain('data-schema-version="9"')
    expect(cleaned).toContain('<span class="highlight" data-annotation="%7B%7D">quoted</span>')
    expect(cleaned).toContain('data-citation="%7B%7D"')
    expect(cleaned).toContain('style="text-align: center"')
    expect(cleaned).toContain('style="color: #ff2020"')
    expect(cleaned).toContain('<td>cell</td>')
  })

  it("drops a class that would borrow the interface's own", () => {
    expect(cleanNote('<p class="modal highlight">Hi</p>')).toBe('<p class="highlight">Hi</p>')
    expect(cleanNote('<p class="modal">Hi</p>')).toBe('<p>Hi</p>')
  })

  it('opens a link elsewhere and tells it nothing', () => {
    const cleaned = cleanNote('<a href="https://example.org">site</a>')

    expect(cleaned).toContain('href="https://example.org"')
    expect(cleaned).toContain('target="_blank"')
    expect(cleaned).toContain('rel="noopener noreferrer"')
  })

  it('answers an empty string for no note', () => {
    expect(cleanNote(undefined)).toBe('')
    expect(cleanNote('')).toBe('')
  })
})

describe('cleaning a bibliography', () => {
  it('keeps the layout the renderer wrote', () => {
    const html =
      '<div class="csl-bib-body" style="line-height: 1.35; padding-left: 2em; text-indent:-2em;">' +
      '<div class="csl-entry">Doe, J. <i>A study</i>.</div></div>'

    const cleaned = cleanBibliography(html)

    expect(cleaned).toContain('class="csl-bib-body"')
    expect(cleaned).toContain('line-height: 1.35; padding-left: 2em; text-indent: -2em')
    expect(cleaned).toContain('<div class="csl-entry">Doe, J. <i>A study</i>.</div>')
  })

  it('drops a handler however it got there', () => {
    expect(cleanBibliography('<div class="csl-entry"><img src=x onerror="alert(1)"></div>')).not.toMatch(
      /onerror/i,
    )
  })
})
