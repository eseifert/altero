"""Prompt automation must activate the window and respect its native delay."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("enables", [True, False])
def test_inactive_prompt_waits_for_native_button_enablement(enables):
    driver = Path(__file__).parents[1] / "tools/compatibility/desktop_dialogs.js"
    result = subprocess.run(
        ["node", "--input-type=module", "-", str(driver), str(enables)],
        input="""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const enables = process.argv[3] === 'True';
let now = 0, focusedAt = null, clicked = false, closed = false;
let watcher, loaded, tick;
const button = {
  label: 'Reset Group and Sync', hidden: false,
  get disabled() { return !enables || focusedAt === null || now - focusedAt < 1000; },
  set disabled(value) { assert.fail('The driver must not override native enablement'); },
  click() {
    assert.equal(this.disabled, false, 'A disabled button cannot be clicked');
    assert.ok(now - focusedAt >= 1000, 'The native activation delay must elapse');
    clicked = true;
  }
};
const window = {
  location: {href: 'chrome://global/content/commonDialog.xhtml'},
  document: {
    getElementById() { return {textContent: 'Acceptance Group'}; },
    querySelector() { return {getButton(name) { return name === 'accept' ? button : null; }}; }
  },
  addEventListener(type, listener) { assert.equal(type, 'load'); loaded = listener; },
  setTimeout(callback) { callback(); },
  setInterval(callback) { tick = callback; return 1; },
  clearInterval() { tick = null; },
  focus() { focusedAt = now; },
  close() { closed = true; }
};
const context = vm.createContext({
  Date: {now: () => now},
  Services: {ww: {
    registerNotification(value) { watcher = value; },
    unregisterNotification(value) { assert.equal(value, watcher); }
  }}
});
vm.runInContext(readFileSync(process.argv[2], 'utf8'), context);
const dialogs = context.watchAcceptanceDialogs([
  {kind: 'prompt', text: 'Acceptance Group', button: button.label}
]);
watcher.observe(window, 'domwindowopened');
loaded();
assert.equal(clicked, false, 'Loading alone must not click a delayed button');
while (tick && now <= 10000) {
  now += 100;
  tick();
}
if (enables) {
  dialogs.finish();
  assert.equal(clicked, true, 'An initially inactive prompt must receive focus');
  assert.equal(closed, false);
  assert.equal(dialogs.trace.length, 1);
} else {
  assert.throws(() => dialogs.finish(), /Prompt button remained disabled/);
  assert.equal(clicked, false);
  assert.equal(closed, true);
  assert.equal(dialogs.trace.length, 0);
}
""",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
