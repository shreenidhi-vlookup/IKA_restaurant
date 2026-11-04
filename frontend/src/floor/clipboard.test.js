import { test } from 'node:test';
import assert from 'node:assert/strict';
import { copyText } from './clipboard.js';

test('modern clipboard receives the exact multiline text once', async () => {
  const calls = [];
  const navigatorObject = { clipboard: { writeText: async text => calls.push(text) } };
  await copyText('Branch: Southall\nValue: £0.00', { navigatorObject });
  assert.deepEqual(calls, ['Branch: Southall\nValue: £0.00']);
});
test('permission failures propagate without falsely reporting successful fallback', async () => {
  const denied = new Error('Permission denied');
  await assert.rejects(copyText('details', { navigatorObject: { clipboard: { writeText: async () => { throw denied; } } }, documentObject: { createElement() { throw new Error('Fallback must not be invoked'); } } }), error => error === denied);
});
function legacy({ modal = false, succeed = true } = {}) {
  const events = [], field = { style: {}, select() { events.push('select'); }, remove() { events.push('remove'); } };
  const documentObject = { activeElement: { isConnected: true, focus() { events.push('restore-focus'); } }, createElement(tag) { assert.equal(tag, 'textarea'); return field; }, body: { appendChild() { events.push('body-append'); } }, querySelector() { return modal ? { appendChild() { events.push('dialog-append'); } } : null; }, execCommand(command) { assert.equal(command, 'copy'); return succeed; } };
  return { events, field, documentObject };
}
test('fallback copies selected text, removes the temporary field and restores focus', async () => {
  const { events, field, documentObject } = legacy();
  await copyText('exact text', { navigatorObject: {}, documentObject });
  assert.equal(field.value, 'exact text');
  assert.deepEqual(events, ['body-append', 'select', 'remove', 'restore-focus']);
});
test('fallback selects within a native modal rather than its inert background', async () => {
  const { events, documentObject } = legacy({ modal: true });
  await copyText('details', { navigatorObject: {}, documentObject });
  assert.deepEqual(events, ['dialog-append', 'select', 'remove', 'restore-focus']);
});
test('failed fallback still removes the temporary field and reports the failure', async () => {
  const { events, documentObject } = legacy({ succeed: false });
  await assert.rejects(copyText('details', { navigatorObject: {}, documentObject }), { message: 'Could not copy to clipboard' });
  assert.deepEqual(events, ['body-append', 'select', 'remove', 'restore-focus']);
});
