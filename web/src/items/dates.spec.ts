import { describe, expect, it } from 'vitest'

import { dateOrder, strToDate } from './dates'

/*
 * What `Zotero.Date.strToDate` itself answers, at the revision the desktop
 * pins (zotero/utilities 4051881), for each of these in each locale: run once
 * in Node against the original `date.js`, as a client with Zotero's day
 * suffixes, and written down here. A two-digit
 * year depends on the day it is read, so they are read as of 26 October 2026.
 */
const TODAY = new Date(2026, 9, 26)

const DESKTOP: [string, string, Record<string, unknown>][] = [
  ["en-US", "1985", {"order": "y", "year": "1985"}],
  ["en-US", "2026-10-26", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["en-US", "26.10.2026", {"order": "dmy", "month": 9, "day": 26, "year": "2026"}],
  ["en-US", "10/26/2026", {"order": "mdy", "month": 9, "day": 26, "year": "2026"}],
  ["en-US", "3/4/85", {"order": "mdy", "month": 2, "day": 4, "year": "1985"}],
  ["en-US", "3/4/45", {"order": "mdy", "month": 2, "day": 4, "year": "1945"}],
  ["en-US", "March 3, 1985", {"order": "mdy", "year": "1985", "month": 2, "day": 3}],
  ["en-US", "3 March 1985", {"order": "dmy", "year": "1985", "month": 2, "day": 3}],
  ["en-US", "Summer 1985", {"order": "y", "year": "1985", "part": "Summer"}],
  ["en-US", "circa 1850", {"order": "y", "year": "1850", "part": "circa"}],
  ["en-US", "Oct 2026", {"order": "my", "year": "2026", "month": 9}],
  ["en-US", "2026年10月26日", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["en-US", "13/12/2001", {"order": "dmy", "month": 11, "day": 13, "year": "2001"}],
  ["en-US", "12/13/2001", {"order": "mdy", "month": 11, "day": 13, "year": "2001"}],
  ["en-US", "5th May 2001", {"order": "dmy", "year": "2001", "month": 4, "day": 5}],
  ["en-US", "May 5th, 2001", {"order": "mdy", "year": "2001", "month": 4, "day": 5}],
  ["en-US", "1985-10", {"order": "ym", "year": "1985", "month": 9}],
  ["en-US", "Spring", {"order": "", "part": "Spring"}],
  ["en-US", "", {"order": ""}],
  ["en-US", "  1999  ", {"order": "y", "year": "1999"}],
  ["en-US", "26. Oktober 2026", {"order": "dy", "year": "2026", "day": 26, "part": "Oktober"}],
  ["en-US", "oktober 2026", {"order": "y", "year": "2026", "part": "oktober"}],
  ["en-US", "300 BC", {"order": "y", "year": "300 BC"}],
  ["en-US", "mars 2020", {"order": "my", "year": "2020", "month": 2}],
  ["en-US", "01/02/03", {"order": "mdy", "month": 0, "day": 2, "year": "2003"}],
  ["en-US", "2020/1/2", {"order": "ymd", "year": "2020", "month": 0, "day": 2}],
  ["en-US", "Jan. 4, 1990", {"order": "mdy", "year": "1990", "month": 0, "day": 4}],
  ["en-GB", "1985", {"order": "y", "year": "1985"}],
  ["en-GB", "2026-10-26", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["en-GB", "26.10.2026", {"order": "dmy", "month": 9, "day": 26, "year": "2026"}],
  ["en-GB", "10/26/2026", {"order": "mdy", "month": 9, "day": 26, "year": "2026"}],
  ["en-GB", "3/4/85", {"order": "dmy", "month": 3, "day": 3, "year": "1985"}],
  ["en-GB", "3/4/45", {"order": "dmy", "month": 3, "day": 3, "year": "1945"}],
  ["en-GB", "March 3, 1985", {"order": "mdy", "year": "1985", "month": 2, "day": 3}],
  ["en-GB", "3 March 1985", {"order": "dmy", "year": "1985", "month": 2, "day": 3}],
  ["en-GB", "Summer 1985", {"order": "y", "year": "1985", "part": "Summer"}],
  ["en-GB", "circa 1850", {"order": "y", "year": "1850", "part": "circa"}],
  ["en-GB", "Oct 2026", {"order": "my", "year": "2026", "month": 9}],
  ["en-GB", "2026年10月26日", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["en-GB", "13/12/2001", {"order": "dmy", "month": 11, "day": 13, "year": "2001"}],
  ["en-GB", "12/13/2001", {"order": "mdy", "month": 11, "day": 13, "year": "2001"}],
  ["en-GB", "5th May 2001", {"order": "dmy", "year": "2001", "month": 4, "day": 5}],
  ["en-GB", "May 5th, 2001", {"order": "mdy", "year": "2001", "month": 4, "day": 5}],
  ["en-GB", "1985-10", {"order": "ym", "year": "1985", "month": 9}],
  ["en-GB", "Spring", {"order": "", "part": "Spring"}],
  ["en-GB", "", {"order": ""}],
  ["en-GB", "  1999  ", {"order": "y", "year": "1999"}],
  ["en-GB", "26. Oktober 2026", {"order": "dy", "year": "2026", "day": 26, "part": "Oktober"}],
  ["en-GB", "oktober 2026", {"order": "y", "year": "2026", "part": "oktober"}],
  ["en-GB", "300 BC", {"order": "y", "year": "300 BC"}],
  ["en-GB", "mars 2020", {"order": "my", "year": "2020", "month": 2}],
  ["en-GB", "01/02/03", {"order": "dmy", "month": 1, "day": 1, "year": "2003"}],
  ["en-GB", "2020/1/2", {"order": "ymd", "year": "2020", "month": 0, "day": 2}],
  ["en-GB", "Jan. 4, 1990", {"order": "mdy", "year": "1990", "month": 0, "day": 4}],
  ["de-DE", "1985", {"order": "y", "year": "1985"}],
  ["de-DE", "2026-10-26", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["de-DE", "26.10.2026", {"order": "dmy", "month": 9, "day": 26, "year": "2026"}],
  ["de-DE", "10/26/2026", {"order": "mdy", "month": 9, "day": 26, "year": "2026"}],
  ["de-DE", "3/4/85", {"order": "dmy", "month": 3, "day": 3, "year": "1985"}],
  ["de-DE", "3/4/45", {"order": "dmy", "month": 3, "day": 3, "year": "1945"}],
  ["de-DE", "March 3, 1985", {"order": "mdy", "year": "1985", "month": 2, "day": 3}],
  ["de-DE", "3 March 1985", {"order": "dmy", "year": "1985", "month": 2, "day": 3}],
  ["de-DE", "Summer 1985", {"order": "y", "year": "1985", "part": "Summer"}],
  ["de-DE", "circa 1850", {"order": "y", "year": "1850", "part": "circa"}],
  ["de-DE", "Oct 2026", {"order": "my", "year": "2026", "month": 9}],
  ["de-DE", "2026年10月26日", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["de-DE", "13/12/2001", {"order": "dmy", "month": 11, "day": 13, "year": "2001"}],
  ["de-DE", "12/13/2001", {"order": "mdy", "month": 11, "day": 13, "year": "2001"}],
  ["de-DE", "5th May 2001", {"order": "dmy", "year": "2001", "month": 4, "day": 5}],
  ["de-DE", "May 5th, 2001", {"order": "mdy", "year": "2001", "month": 4, "day": 5}],
  ["de-DE", "1985-10", {"order": "ym", "year": "1985", "month": 9}],
  ["de-DE", "Spring", {"order": "", "part": "Spring"}],
  ["de-DE", "", {"order": ""}],
  ["de-DE", "  1999  ", {"order": "y", "year": "1999"}],
  ["de-DE", "26. Oktober 2026", {"order": "dmy", "year": "2026", "month": 9, "day": 26}],
  ["de-DE", "oktober 2026", {"order": "my", "year": "2026", "month": 9}],
  ["de-DE", "300 BC", {"order": "y", "year": "300 BC"}],
  ["de-DE", "mars 2020", {"order": "my", "year": "2020", "month": 2}],
  ["de-DE", "01/02/03", {"order": "dmy", "month": 1, "day": 1, "year": "2003"}],
  ["de-DE", "2020/1/2", {"order": "ymd", "year": "2020", "month": 0, "day": 2}],
  ["de-DE", "Jan. 4, 1990", {"order": "mdy", "year": "1990", "month": 0, "day": 4}],
  ["fr-FR", "1985", {"order": "y", "year": "1985"}],
  ["fr-FR", "2026-10-26", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["fr-FR", "26.10.2026", {"order": "dmy", "month": 9, "day": 26, "year": "2026"}],
  ["fr-FR", "10/26/2026", {"order": "mdy", "month": 9, "day": 26, "year": "2026"}],
  ["fr-FR", "3/4/85", {"order": "dmy", "month": 3, "day": 3, "year": "1985"}],
  ["fr-FR", "3/4/45", {"order": "dmy", "month": 3, "day": 3, "year": "1945"}],
  ["fr-FR", "March 3, 1985", {"order": "mdy", "year": "1985", "month": 2, "day": 3}],
  ["fr-FR", "3 March 1985", {"order": "dmy", "year": "1985", "month": 2, "day": 3}],
  ["fr-FR", "Summer 1985", {"order": "y", "year": "1985", "part": "Summer"}],
  ["fr-FR", "circa 1850", {"order": "y", "year": "1850", "part": "circa"}],
  ["fr-FR", "Oct 2026", {"order": "my", "year": "2026", "month": 9}],
  ["fr-FR", "2026年10月26日", {"order": "ymd", "year": "2026", "month": 9, "day": 26}],
  ["fr-FR", "13/12/2001", {"order": "dmy", "month": 11, "day": 13, "year": "2001"}],
  ["fr-FR", "12/13/2001", {"order": "mdy", "month": 11, "day": 13, "year": "2001"}],
  ["fr-FR", "5th May 2001", {"order": "dmy", "year": "2001", "month": 4, "day": 5}],
  ["fr-FR", "May 5th, 2001", {"order": "mdy", "year": "2001", "month": 4, "day": 5}],
  ["fr-FR", "1985-10", {"order": "ym", "year": "1985", "month": 9}],
  ["fr-FR", "Spring", {"order": "", "part": "Spring"}],
  ["fr-FR", "", {"order": ""}],
  ["fr-FR", "  1999  ", {"order": "y", "year": "1999"}],
  ["fr-FR", "26. Oktober 2026", {"order": "dy", "year": "2026", "day": 26, "part": "Oktober"}],
  ["fr-FR", "oktober 2026", {"order": "y", "year": "2026", "part": "oktober"}],
  ["fr-FR", "300 BC", {"order": "y", "year": "300 BC"}],
  ["fr-FR", "mars 2020", {"order": "my", "year": "2020", "month": 2}],
  ["fr-FR", "01/02/03", {"order": "dmy", "month": 1, "day": 1, "year": "2003"}],
  ["fr-FR", "2020/1/2", {"order": "ymd", "year": "2020", "month": 0, "day": 2}],
  ["fr-FR", "Jan. 4, 1990", {"order": "mdy", "year": "1990", "month": 0, "day": 4}],
]

describe('strToDate', () => {
  it.each(DESKTOP)('reads %s %j as the desktop does', (locale, value, expected) => {
    expect({ ...strToDate(value, locale, TODAY) }).toEqual(expected)
  })
})

describe('dateOrder', () => {
  it('spaces the order out as the item pane draws it', () => {
    expect(dateOrder('26.10.2026', 'de-DE')).toBe('d m y')
    expect(dateOrder('10/26/2026', 'en-US')).toBe('m d y')
  })

  it('draws nothing for a date it cannot read', () => {
    expect(dateOrder('Spring', 'en-US')).toBe('')
  })
})
