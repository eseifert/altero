import assert from 'node:assert/strict'
import { test } from 'node:test'

import { checkCatalogs } from './check-locales.ts'

test('wording, repeated placeholders and additional plural forms are allowed', () => {
  assert.deepEqual(checkCatalogs({
    'en-US': { greeting: 'Hello {person}', count: '{n} one | {n} many' },
    xx: { greeting: 'Anything {person}, {person}', count: '{n} A | {n} B | {n} C' },
  }), { errors: [], warnings: [] })
})

test('missing and obsolete keys only warn', () => {
  const result = checkCatalogs({ 'en-US': { current: 'A' }, xx: { old: 'B' } })
  assert.deepEqual(result.errors, [])
  assert.equal(result.warnings.length, 2)
})

test('invalid message syntax and non-string exports fail', () => {
  for (const catalog of [null, [], { bad: 12 }, { bad: 'Unclosed {name' }]) {
    assert.ok(checkCatalogs({ 'en-US': { bad: 'Fine' }, xx: catalog }).errors.length)
  }
  assert.ok(checkCatalogs({}).errors.length)
})

test('each branch must preserve named and positional placeholders', () => {
  const source = { count: '{n} {0} one | {n} {0} many' }
  for (const text of ['{n} A | {n} {0} B', '{n} {0} A | {other} {0} B']) {
    assert.match(checkCatalogs({ 'en-US': source, xx: { count: text } }).errors.join(), /placeholders/)
  }
})

test('literal braces and pipes are not placeholders or plural branches', () => {
  assert.deepEqual(checkCatalogs({
    'en-US': { literal: "{'{'}name{'}'} {'|'} {name}" },
    xx: { literal: "{'|'} {name}" },
  }).errors, [])
  assert.match(checkCatalogs({
    'en-US': { single: 'One' }, xx: { single: 'A | B' },
  }).errors.join(), /unexpected plural/)
})
