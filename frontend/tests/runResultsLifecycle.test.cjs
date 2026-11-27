// Run with: node --test tests/runResultsLifecycle.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(file, deps) {
  const result = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, reportDiagnostics: true,
  });
  assert.equal(result.diagnostics.filter(d => d.category === ts.DiagnosticCategory.Error).length, 0);
  const exports = {};
  vm.runInNewContext(result.outputText, { exports, Error, require: name => { if (!(name in deps)) throw new Error(name); return deps[name]; } });
  return exports;
}
function setup() {
  const run = { resultsRunId: null, busy: false, output: { active: false }, plan: null, autoAnalysisRequestedFor: null };
  const runtime = { runActive: false, lastFinishedRecording: null };
  const calls = [], queries = [], effects = [];
  const client = { setQueryData() {}, invalidateQueries() {} };
  const useExperimentRun = Object.assign(fn => fn(run), { getState: () => run, setState: update => Object.assign(run, update) });
  let attempts = new Set(), failure = null, mutationOptions;
  const history = [{ run_id: 'old' }];
  const hook = load('src/services/useRunValidation.ts', {
    react: { useEffect: fn => effects.push(fn), useRef: () => ({ current: attempts }), useState: () => [failure, update => { failure = typeof update === 'function' ? update(failure) : update; }] },
    '@tanstack/react-query': { useQueryClient: () => client, useQuery: opts => {
      queries.push(opts);
      const [type, id] = opts.queryKey;
      // Deliberately expose cached data even with disabled queries, to test masking.
      const data = type === 'recorded-runs' ? { runs: history } : type === 'recorded-run' ? { run_id: id || 'stale', status: 'completed', playback: { status: 'stopped' } } : { run_id: id || 'stale', matching: { status: 'matched' } };
      return { data, isPending: false, error: null };
    }, useMutation: opts => { mutationOptions = opts; return { mutate: args => calls.push(args), isPending: false }; } },
    '../state/api': { api: {} }, '../state/store': { useRuntime: fn => fn(runtime) }, './experimentRun': { useExperimentRun },
  }).useRunValidation;
  const render = () => { effects.length = 0; queries.length = 0; const result = hook(); for (const effect of effects) effect(); return result; };
  return { run, runtime, calls, queries, render, remount: () => { attempts = new Set(); failure = null; }, failAnalysis: id => mutationOptions.onError(new Error('old failure'), { runId: id }) };
}
test('startup with saved history is blank and never auto-selects or analyzes it', () => {
  const s = setup(); const r = s.render();
  assert.equal(r.runs.length, 1); assert.equal(r.selectedRunId, null); assert.equal(r.report, null); assert.equal(r.manifest, null);
  assert.equal(s.queries[1].enabled, false); assert.equal(s.queries[2].enabled, false);
  assert.equal(s.calls.length, 0); assert.equal(s.run.resultsRunId, null);
});
test('explicit history selection and clearing work and remain stable on remount', () => {
  const s = setup(); s.render().setSelectedRunId('old');
  let r = s.render(); assert.equal(r.report.run_id, 'old'); assert.equal(r.manifest.run_id, 'old');
  s.remount(); r = s.render(); assert.equal(r.selectedRunId, 'old');
  r.setSelectedRunId(''); r = s.render(); assert.equal(r.selectedRunId, null); assert.equal(r.report, null);
  assert.equal(s.calls.length, 0);
});
test('arming, playback and stopping hide all historical results and disable selection', () => {
  const s = setup(); s.render().setSelectedRunId('old');
  for (const stage of [{ busy: true, active: false, uart: false }, { busy: false, active: true, uart: true }, { busy: true, active: false, uart: false }]) {
    s.run.busy = stage.busy; s.run.output.active = stage.active; s.runtime.runActive = stage.uart;
    const r = s.render(); assert.equal(r.busy, true); assert.equal(r.selectedRunId, null); assert.equal(r.report, null); assert.equal(r.manifest, null);
    r.setSelectedRunId('other'); assert.equal(s.run.resultsRunId, 'old');
  }
  assert.equal(s.calls.length, 0);
});
test('new recording is selected and analyzed once after final stop, not while draining', () => {
  const s = setup(); s.run.plan = { recording_run_id: 'new' }; s.run.busy = true;
  s.runtime.lastFinishedRecording = { run_id: 'new', mode: 'events', recording_status: 'completed' };
  s.render(); assert.equal(s.calls.length, 0);
  s.run.busy = false; s.render(); const r = s.render();
  assert.equal(r.selectedRunId, 'new'); assert.equal(r.report.run_id, 'new'); assert.equal(s.calls.length, 1); assert.equal(s.calls[0].runId, 'new');
  r.setSelectedRunId('old'); s.remount(); assert.equal(s.render().selectedRunId, 'old');
  s.render().setSelectedRunId(''); s.remount(); assert.equal(s.render().selectedRunId, null); assert.equal(s.calls.length, 1);
});
test('failed startup or GPIO diagnostic does not resurrect an earlier result', () => {
  const s = setup(); s.runtime.lastFinishedRecording = { run_id: 'old', mode: 'events' };
  s.run.autoAnalysisRequestedFor = 'old'; s.render(); assert.equal(s.run.resultsRunId, null);
  s.run.plan = { recording_run_id: 'gpio' }; s.runtime.lastFinishedRecording = { run_id: 'gpio', mode: 'gpio' };
  s.render(); assert.equal(s.run.resultsRunId, null); assert.equal(s.calls.length, 0);
});
test('late analysis errors from another run stay hidden', () => {
  const s = setup(); s.render().setSelectedRunId('new'); s.render(); s.failAnalysis('old');
  assert.equal(s.render().analysisError, null); s.failAnalysis('new'); assert.equal(s.render().analysisError, 'old failure');
});
