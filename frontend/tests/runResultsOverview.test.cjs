// Run with: node --test tests/runResultsOverview.test.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(file, dependencies = {}) {
  const result = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }, reportDiagnostics: true,
  });
  assert.equal(result.diagnostics.filter(d => d.category === ts.DiagnosticCategory.Error).length, 0);
  const exports = {};
  vm.runInNewContext(result.outputText, { exports, require: name => {
    if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
    return dependencies[name];
  }});
  return exports;
}
const jsx = (type, props) => ({ type, props });
const modules = { 'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: Symbol('fragment') }, react: { useState: initial => [initial, () => {}] }, '../state/api': { api: {} }, '../services/validationRuns': load('src/services/validationRuns.ts') };
const { ResultsOverview, PerformanceSummary, ReferenceComparison, ValidationBanner } = load('src/components/RunValidationPanels.tsx', modules);
function textOf(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (Array.isArray(node)) return node.map(textOf).join(' ');
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (typeof node.type === 'function') return textOf(node.type(node.props));
  return textOf(node.props?.children);
}
function report() {
  return {
    validation: { performance_summary: [
      { name: 'Peak accuracy (isolated)', value: 1, units: 'fraction', target: '≥ 90%', status: 'PASS', reason: 'Independent digital stimulus classification' },
      { name: 'Timestamp max |error|', value: null, units: 'µs', target: '< 100', status: 'NOT_AVAILABLE', reason: 'No shared origin' },
      { name: 'Data reduction', value: '≤4.00', units: '×', target: '≥ 10', status: 'FAIL', reason: 'Bandwidth exceeded' },
    ], metrics: { detection: { precision: 1, recall: .999 }, data_reduction: { baseline: { continuous_bit_rate_bps: 160000 }, gross_uart_bit_rate_bps: 40000 } }, warnings: [] },
    matching: { status: 'exploratory', counts: { expected: 4008, observed: 4004, tp: 4004, fp: 0, fn: 4 }, alignment: { mode: 'event_anchor', explanation: 'Estimated', absolute_timing_available: false }, tolerance_us: 100, matches: [], false_negatives: [], false_positives: [] },
    relative_timing: { consecutive_pairs: 4003, mean_absolute_interval_error_us: .493, max_absolute_interval_error_us: .560, cumulative_relative_drift_us: -7.680, relative_clock_error_ppm: -.768, max_absolute_anchored_residual_us: 8.480, warnings: [] },
    hardware_sync: { status: 'NOT_AVAILABLE' }, capture_reconciliation: { complete: false }, verification_audit: { software_verified_count: 4, total_checks: 7, checks: [] },
    input_snapshots: { playback_duration_s_host_observed: 10, sample_rate_hz: 204800 }, warnings: [],
  };
}
test('overview displays counts, metric decisions, timing, and evidence together', () => {
  const text = textOf(ResultsOverview({ report: report() })).replace(/\s+/g, " ");
  for (const token of ['1 passed', '1 failed', '1 not verified', 'PCB not tested', '4,008', '4,004', 'Missing (FN) 4', 'Extra (FP) 0', '0.493 µs', '0.560 µs', '-7.680 µs', '-0.768 ppm', 'Exploratory alignment', 'Diagnostic only', 'Not verified', '40.00 kbit/s', '4/7', '≤4.00×']) assert.ok(text.includes(token), token);
});
test('missing evidence and unavailable metrics remain unknown, not zero or PASS', () => {
  const r = report(); r.matching.counts.tp = r.matching.counts.fp = r.matching.counts.fn = null; r.matching.status = 'alignment_required'; delete r.relative_timing; delete r.verification_audit; r.validation.metrics.detection.precision = null; r.validation.metrics.detection.recall = null; r.validation.metrics.data_reduction.gross_uart_bit_rate_bps = null;
  const text = textOf(ResultsOverview({ report: r })).replace(/\s+/g, " ");
  for (const token of ['Matched (TP) —', 'Extra (FP) —', 'Missing (FN) —', 'Mean interval error (abs.) —', 'Precision —', 'Gross UART —', 'Evidence checks —', 'Alignment required']) assert.ok(text.includes(token), token);
  assert.match(textOf(ResultsOverview({ report: null })), /when analysis is available/);
});
test('detail panels retain backend reasons and advanced alignment diagnostics', () => {
  const r = report();
  const text = textOf(PerformanceSummary({ report: r }));
  assert.match(text, /No shared origin/); assert.match(text, /Bandwidth exceeded/);
  const comparison = textOf(ReferenceComparison({ report: r, onAnalyze() {}, disabled: false, validating: false }));
  assert.match(comparison, /Exploratory event alignment/); assert.match(comparison, /8.480/);
});
test('compact banner preserves analysis error and blocks reanalysis while busy', () => {
  const tree = ValidationBanner({ report: report(), manifest: { playback: { status: 'stopped' } }, loading: false, validating: false, error: 'test failure', onAnalyze() {}, disabled: true });
  assert.match(textOf(tree), /test failure/);
  assert.equal(tree.props.children[1].props.disabled, true);
});

test('history selector always includes a blank option and is locked during a run', () => {
  const { RunSelector } = load('src/components/RunValidationPanels.tsx', modules);
  const run = { run_id: 'old', armed_at_utc: '2026-11-25T12:00:00Z', playback: { config: { dataset: 'separated' } }, status: 'completed' };
  const tree = RunSelector({ runs: [run], selectedRunId: 'old', loading: false, busy: true, error: null, onChange() {} });
  const select = tree.props.children[1];
  assert.equal(select.props.disabled, true); assert.equal(select.props.children[0].props.value, '');
  assert.match(textOf(select), /Select a saved experiment/);
});
