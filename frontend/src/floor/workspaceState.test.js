import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BRANCHES, SECTIONS, createWorkspaceState, workspaceReducer, isBusinessDate, localBusinessDate, sectionFromHash } from './workspaceState.js';

test('preview branch values exactly match the working application', () => {
  const original = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  const declaration = original.match(/const BRANCHES = \[([^\]]+)\]/)[1];
  const originalValues = [...declaration.matchAll(/'([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(BRANCHES, originalValues);
});

test('all five sections retain the selected API branch and business date', () => {
  assert.deepEqual(SECTIONS.map(section => section.label), ['Overview', 'Imports', 'Tickets', 'Verification', 'Reports']);
  for (const branch of BRANCHES) {
    let state = createWorkspaceState({ now: new Date(2026, 10, 3) });
    state = workspaceReducer(state, { type: 'branch', value: branch });
    state = workspaceReducer(state, { type: 'businessDate', value: '2027-02-18' });
    for (const section of [...SECTIONS, ...SECTIONS.toReversed()]) {
      state = workspaceReducer(state, { type: 'section', value: `#${section.id}` });
      assert.equal(state.section, section.id);
      assert.equal(state.branch, branch);
      assert.equal(state.businessDate, '2027-02-18');
    }
  }
});

test('changing context on a section preserves the other selection and active section', () => {
  const initial = { branch: BRANCHES[0], businessDate: '2026-11-03', section: 'verification' };
  const changed = workspaceReducer(initial, { type: 'branch', value: BRANCHES[1] });
  assert.deepEqual(changed, { ...initial, branch: BRANCHES[1] });
  assert.deepEqual(workspaceReducer(changed, { type: 'businessDate', value: '2026-11-04' }), { ...changed, businessDate: '2026-11-04' });
  assert.deepEqual(initial, { branch: BRANCHES[0], businessDate: '2026-11-03', section: 'verification' });
});

test('defaults use the local calendar date and support deep-linked sections', () => {
  const now = new Date(2028, 1, 29, 23, 59);
  assert.equal(localBusinessDate(now), '2028-02-29');
  assert.deepEqual(createWorkspaceState({ now, hash: '#reports' }), { branch: '', businessDate: '2028-02-29', section: 'reports' });
  assert.equal(sectionFromHash('#not-a-section'), 'overview');
  assert.equal(sectionFromHash('#hf-main'), 'overview');
});

test('invalid dates and mock branch slugs cannot enter shared API context', () => {
  const state = createWorkspaceState({ now: new Date(2026, 10, 3) });
  for (const value of ['', '2026-02-29', '2026-04-31', '2026-13-01', '0000-01-01', 'not-a-date']) {
    assert.equal(isBusinessDate(value), false);
    assert.equal(workspaceReducer(state, { type: 'businessDate', value }), state);
  }
  assert.equal(isBusinessDate('2028-02-29'), true);
  assert.equal(workspaceReducer(state, { type: 'branch', value: 'southall' }), state);
  assert.equal(workspaceReducer({ ...state, branch: BRANCHES[0] }, { type: 'branch', value: '' }).branch, '');
});
