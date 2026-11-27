// Run: node --test tests/neuralEventHistory.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(relative, dependencies = {}) {
  const js = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(js, { exports, require: name => dependencies[name] });
  return exports;
}
function create(init) {
  if (!init) return create;
  let state;
  const set = value => { state = { ...state, ...(typeof value === 'function' ? value(state) : value) }; };
  state = init(set);
  return { getState: () => state };
}
const sample = (timestamp_us, flags_mask = 0) => ({ timestamp_us, channel: 0, peak: 3, trough: 4,
  time_to_peak_us: 97, flags_mask, raw_hex: 'AA 02 00 00 00 00 00 00 00 00',
  flags: { timeout: !!flags_mask, saturation: false, overlap: false, invalid_sequence: false } });
const stats = received => ({ received, timeouts: 0, saturations: 0, overlaps: 0, invalid_sequences: 0 });

test('store retains every received event beyond old 250-event cap, survives disconnect, clears at next arm', () => {
  const { useRuntime } = load('src/state/store.ts', { zustand: { create }, 'zustand/middleware': { persist: x => x } });
  const state = () => useRuntime.getState();
  state().recordingStarted('run-a', 'events');
  state().clearNeuralEvents();
  for (let batch = 0; batch < 100; batch++) {
    state().appendNeuralEvents(Array.from({ length: 40 }, (_, i) => sample(batch * 40 + i)), stats((batch + 1) * 40));
  }
  assert.equal(state().neuralEvents.length, 4000);
  assert.equal(state().neuralEvents[0].timestamp_us, 0);
  assert.equal(state().neuralEvents[3999].timestamp_us, 3999);
  state().setSerial(false, 'Disconnected');
  assert.equal(state().neuralEvents.length, 4000);
  assert.equal(state().neuralRunId, 'run-a');
  assert.equal(state().neuralStats.received, 4000);
  state().recordingStarted('run-b', 'events');
  state().clearNeuralEvents();
  assert.equal(state().neuralEvents.length, 0);
  assert.equal(state().neuralRunId, 'run-b');
  assert.equal(state().neuralStats, null);
});
test('CSV includes complete capture and preserves wrap order, raw hex and decoded flag columns', () => {
  const { neuralEventsCsv } = load('src/services/neuralEventCsv.ts');
  const events = Array.from({length: 4004}, (_, i) => sample((16777214 + i) % 16777216, i === 2 ? 4 : 0));
  const lines = neuralEventsCsv(events).trimEnd().split('\r\n');
  assert.equal(lines.length, 4005);
  assert.match(lines[1], /^1,16777214,0,3,4,97,0,0,0,0,0,"AA 02/);
  assert.match(lines[3], /^3,0,0,3,4,97,4,1,0,0,0,/);
  assert.match(lines[4004], /^4004,4001,/);
});
