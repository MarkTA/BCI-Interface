// Run with: node --test tests/experimentRunRecovery.test.cjs
// Exercises the actual TypeScript service against mocked device/serial APIs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function create(init) {
  let state;
  const listeners = new Set();
  const setState = update => {
    state = { ...state, ...(typeof update === 'function' ? update(state) : update) };
    for (const listener of listeners) listener(state);
  };
  state = init(setState);
  return { getState: () => state, setState, subscribe: fn => {
    listeners.add(fn); return () => listeners.delete(fn);
  } };
}

function setup({ connected = false, active = false } = {}) {
  const runtime = create(set => ({
    serialConnected: connected, serialMock: false, runActive: active, lastSerialPort: "COM6", lastSerialBaud: 115200,
    ad3Status: 'connected', appliedSignature: 'match', thresholdAcks: { 0: 'ack' }, fpgaVerified: true, thresholdSendStatus: 'idle',
    setRunActive: runActive => set({ runActive }), setAd3Status: ad3Status => set({ ad3Status }),
    clearGpioTrace() {}, addLog() {},
  }));
  const config = create(() => ({ signalSource: 'ad3', datasetName: 'small_spike', thresholdsMv: [1,2,3,4,-1,-2,-3,-4] }));
  const serial = {
    disconnect() { runtime.setState({ serialConnected: false, runActive: false, appliedSignature: null, thresholdAcks: {}, fpgaVerified: false }); },
    setRunActive(active) { runtime.setState({ runActive: active }); return true; },
    async stopRun() { runtime.setState({ runActive: false }); return []; },
    async armRun() { runtime.setState({ runActive: true }); },
    async reconnect() { runtime.setState({ serialConnected: true, appliedSignature: null, fpgaVerified: false, thresholdAcks: {} }); },
  };
  const api = {
    async digitalStatus() { return { active: false, mode: 'idle', outputs_low: true }; },
    async digitalStop() { return { active: false, mode: 'idle', outputs_low: true }; },
    async ad3Connection() { return { ready: true, message: "AD3 scope acquisition successful" }; },
    async comparatorPreview() { return { warning: null }; },
    async comparatorStart() { throw new Error('Digital Out config failed'); },
  };
  const threshold = { AFE_BIAS_V: 1.6, validThresholds: () => true, async sendThresholdsToFpga() { runtime.setState({ appliedSignature: "match", fpgaVerified: true }); } };
  const dependencies = {
    zustand: { create }, '../state/api': { api }, '../state/store': { useConfig: config, useRuntime: runtime, thresholdSignature: () => 'match' },
    './fpgaSerial': { fpgaSerial: serial }, './thresholdConfiguration': threshold,
  };
  const filename = path.join(__dirname, '../src/services/experimentRun.ts');
  const js = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(js, { exports, require: name => dependencies[name], setTimeout, clearTimeout, setInterval, clearInterval });
  return { service: exports, runtime, api, serial, threshold };
}

test('failed REST stop exits Running and remains recoverable with UART disconnected', async () => {
  const { service, runtime, api } = setup();
  service.useExperimentRun.setState({ output: { active: true, mode: 'comparators' } });
  api.digitalStop = async () => { throw new Error('Digital Out config failed'); };
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required', outputs_low: false, error: 'Digital Out config failed' });
  await service.stopExperiment();
  const state = service.useExperimentRun.getState();
  assert.equal(state.busy, false);
  assert.equal(runtime.getState().runActive, false);
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.equal(service.isExperimentRunning(), false);
  assert.equal(service.requiresRecovery(state.output), true);
  assert.match(state.error, /Analog Discovery digital output/);
  assert.match(state.errorDetails, /Digital Out config failed/);
  api.digitalStop = async () => ({ active: false, mode: 'idle', outputs_low: true });
  await service.stopExperiment();
  assert.equal(service.requiresRecovery(service.useExperimentRun.getState().output), false);
  assert.equal(service.useExperimentRun.getState().busy, false);
});

test('FPGA Stop ACK alone does not clear an AD recovery fault', async () => {
  const { service, runtime, api } = setup({ connected: true, active: true });
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required', outputs_low: false });
  await service.stopExperiment();
  assert.equal(service.useExperimentRun.getState().busy, false);
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().appliedSignature, 'match');
  assert.equal(service.requiresRecovery(service.useExperimentRun.getState().output), true);
});

test('normal stop keeps UART connected', async () => {
  const { service, runtime } = setup({ connected: true, active: true });
  await service.stopExperiment();
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(service.isExperimentRunning(), false);
  assert.equal(service.useExperimentRun.getState().busy, false);
  assert.equal(service.useExperimentRun.getState().error, null);
});

test('AD startup failure after FPGA arm is cleaned up', async () => {
  const { service, runtime, api } = setup({ connected: true });
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required', outputs_low: false, error: 'Digital Out config failed' });
  await service.startExperiment('events');
  assert.equal(service.useExperimentRun.getState().busy, false);
  assert.equal(service.isExperimentRunning(), false);
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.match(service.useExperimentRun.getState().error, /Analog Discovery digital output/);
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().appliedSignature, 'match');
});

test('starting a new run clears the session result selection even on startup failure', async () => {
  const { service } = setup({ connected: true });
  assert.equal(service.useExperimentRun.getState().resultsRunId, null);
  service.useExperimentRun.setState({ resultsRunId: 'old-recording' });
  await service.startExperiment('events');
  assert.equal(service.useExperimentRun.getState().resultsRunId, null);
});


test('unplug before Start keeps UART and thresholds; explicit recovery can retry', async () => {
  const { service, runtime, api, serial } = setup({ connected: true });
  const raw = 'FDwfDeviceOpen: No connected device found FDwfDeviceOpenEx';
  let stopCalls = 0;
  api.comparatorStart = async () => { throw new Error(raw); };
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required', outputs_low: false, error: raw });
  api.digitalStop = async () => { stopCalls++; throw new Error(raw); };
  serial.stopRun = async () => { runtime.setState({ runActive: false }); return [`AD3 recovery required: ${raw}`]; };
  await service.startExperiment('events');
  let state = service.useExperimentRun.getState();
  assert.match(state.error, /Analog Discovery was not detected/);
  assert.match(state.error, /UART remains connected/);
  assert.match(state.errorDetails, /FDwfDeviceOpen/);
  assert.equal(stopCalls, 0); // no immediate reopen of absent USB device
  assert.equal(state.busy, false);
  assert.equal(service.isExperimentRunning(), false);
  assert.equal(service.requiresRecovery(state.output), true);
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().fpgaVerified, true);
  assert.equal(runtime.getState().thresholdAcks[0], 'ack');
  await service.stopExperiment(); // device still missing
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(service.requiresRecovery(service.useExperimentRun.getState().output), true);
  api.digitalStop = async () => ({ active: false, mode: 'idle', outputs_low: true });
  await service.stopExperiment(); // device reconnected
  state = service.useExperimentRun.getState();
  assert.equal(state.error, null);
  assert.equal(state.errorDetails, null);
  assert.equal(service.requiresRecovery(state.output), false);
  assert.equal(runtime.getState().ad3Status, 'connected'); // recovery performs readiness check
  assert.equal(runtime.getState().appliedSignature, 'match');
});

test('serial cleanup failure alone uses disconnect fallback', async () => {
  const { service, runtime, serial } = setup({ connected: true, active: true });
  serial.stopRun = async () => { throw new Error('Serial bridge did not confirm run cleanup'); };
  await service.stopExperiment();
  assert.equal(runtime.getState().serialConnected, false);
  assert.equal(service.isExperimentRunning(), false);
  assert.match(service.useExperimentRun.getState().error, /UART was disconnected because recording cleanup/);
  assert.equal(runtime.getState().ad3Status, 'connected');
});

test('a status request failure after stop ACK does not disconnect UART', async () => {
  const { service, runtime, api } = setup({ connected: true, active: true });
  api.digitalStatus = async () => { throw new Error('Failed to fetch'); };
  await service.stopExperiment();
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(service.requiresRecovery(service.useExperimentRun.getState().output), true);
  assert.equal(service.isExperimentRunning(), false);
});

test('failed FPGA arm is cleaned up even when local runActive never became true', async () => {
  const { service, runtime, serial } = setup({ connected: true });
  let stopCalls = 0;
  serial.armRun = async () => { throw new Error('FPGA GPIO/sync arm not confirmed'); };
  serial.stopRun = async () => { stopCalls++; return []; };
  await service.startExperiment('events');
  assert.equal(stopCalls, 1);
  assert.equal(runtime.getState().serialConnected, false);
  assert.equal(runtime.getState().fpgaVerified, false);
  assert.equal(runtime.getState().ad3Status, 'connected');
  assert.match(service.useExperimentRun.getState().error, /FPGA communication could not be verified/);
});

test('counter verification warning is visible without disconnecting UART', async () => {
  const { service, runtime, serial } = setup({ connected: true, active: true });
  serial.stopRun = async () => { runtime.setState({ runActive: false }); return ['FPGA capture counters not confirmed: timeout']; };
  await service.stopExperiment();
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().ad3Status, 'connected');
  assert.match(service.useExperimentRun.getState().errorDetails, /capture counters/);
});


test('recovery waits for readiness before restoring AD3 verification; preserves FPGA state', async () => {
  const { service, runtime, api } = setup({ connected: true });
  runtime.setState({ ad3Status: 'failed' });
  service.useExperimentRun.setState({ output: { active: false, mode: 'recovery_required' } });
  let release;
  let started;
  const startedCheck = new Promise(resolve => { started = resolve; });
  api.ad3Connection = () => { started(); return new Promise(resolve => { release = resolve; }); };
  const recovery = service.stopExperiment();
  await startedCheck;
  assert.equal(runtime.getState().ad3Status, 'checking');
  assert.equal(service.useExperimentRun.getState().busy, true);
  release({ ready: true });
  await recovery;
  assert.equal(runtime.getState().ad3Status, 'connected');
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().fpgaVerified, true);
  assert.equal(runtime.getState().appliedSignature, 'match');
  assert.equal(service.useExperimentRun.getState().busy, false);
});

test('failed stop does not run readiness check', async () => {
  const { service, runtime, api } = setup({ connected: true });
  runtime.setState({ ad3Status: 'failed' });
  service.useExperimentRun.setState({ output: { active: false, mode: 'recovery_required' } });
  let checks = 0;
  api.ad3Connection = async () => { checks++; return { ready: true }; };
  api.digitalStop = async () => { throw new Error('USB disconnected'); };
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required' });
  await service.stopExperiment();
  assert.equal(checks, 0);
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.equal(runtime.getState().serialConnected, true);
});

test('failed readiness stays failed and can be retried from the idle Run section', async () => {
  const { service, runtime, api } = setup({ connected: true });
  runtime.setState({ ad3Status: 'failed' });
  service.useExperimentRun.setState({ output: { active: false, mode: 'recovery_required' } });
  api.ad3Connection = async () => ({ ready: false, message: 'scope acquisition timed out' });
  await service.stopExperiment();
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.match(service.useExperimentRun.getState().error, /did not pass its connection test/);
  assert.match(service.useExperimentRun.getState().errorDetails, /scope acquisition timed out/);
  assert.equal(runtime.getState().serialConnected, true);
  assert.equal(runtime.getState().appliedSignature, 'match');
  api.ad3Connection = async () => ({ ready: true });
  await service.stopExperiment();
  assert.equal(runtime.getState().ad3Status, 'connected');
  assert.equal(service.useExperimentRun.getState().error, null);
});

test('readiness request failure preserves backend recovery state and UART', async () => {
  const { service, runtime, api } = setup({ connected: true });
  runtime.setState({ ad3Status: 'failed' });
  service.useExperimentRun.setState({ output: { active: false, mode: 'recovery_required' } });
  api.ad3Connection = async () => { throw new Error('Failed to fetch'); };
  api.digitalStatus = async () => ({ active: false, mode: 'recovery_required', outputs_low: false });
  await service.stopExperiment();
  assert.equal(runtime.getState().ad3Status, 'failed');
  assert.equal(service.requiresRecovery(service.useExperimentRun.getState().output), true);
  assert.equal(runtime.getState().serialConnected, true);
});

test('normal experiment stop does not perform another readiness acquisition', async () => {
  const { service, runtime, api } = setup({ connected: true, active: true });
  let checks = 0;
  api.ad3Connection = async () => { checks++; return { ready: true }; };
  await service.stopExperiment();
  assert.equal(checks, 0);
  assert.equal(runtime.getState().ad3Status, 'connected');
});


test('recovery uses the saved port and baud, waits for fresh verification, preserves AD3', async () => {
  const { service, runtime, serial, threshold, api } = setup();
  runtime.setState({ fpgaVerified: false, appliedSignature: null, lastSerialPort: 'COM6', lastSerialBaud: 115200 });
  const calls = [];
  serial.reconnect = async (port, baud) => { calls.push([port, baud]); runtime.setState({ serialConnected: true }); };
  let release, started;
  const entered = new Promise(resolve => { started = resolve; });
  threshold.sendThresholdsToFpga = async () => { started(); await new Promise(resolve => { release = resolve; }); runtime.setState({ appliedSignature: 'match', fpgaVerified: true }); };
  api.ad3Connection = async () => { throw new Error('must not retest AD3'); };
  const recovery = service.recoverFpga();
  await entered;
  assert.deepEqual(calls, [['COM6',115200]]);
  assert.equal(service.useExperimentRun.getState().busy, true);
  assert.equal(service.canArmExperiment(), false);
  release(); await recovery;
  assert.equal(service.canArmExperiment(), true);
  assert.equal(runtime.getState().ad3Status, 'connected');
  assert.equal(service.useExperimentRun.getState().error, null);
});

test('FTDI reopen without FPGA ACKs stays unverified and can retry', async () => {
  const { service, runtime, threshold } = setup();
  threshold.sendThresholdsToFpga = async () => { runtime.setState({ thresholdSendMessage: 'FPGA threshold acknowledgment timed out' }); };
  await service.recoverFpga();
  assert.equal(runtime.getState().serialConnected, false);
  assert.equal(runtime.getState().fpgaVerified, false);
  assert.equal(service.useExperimentRun.getState().busy, false);
  assert.match(service.useExperimentRun.getState().error, /FPGA reconnection failed/);
  assert.equal(runtime.getState().ad3Status, 'connected');
  threshold.sendThresholdsToFpga = async () => { runtime.setState({ appliedSignature: 'match', fpgaVerified: true }); };
  await service.recoverFpga();
  assert.equal(service.canArmExperiment(), true);
});

test('missing COM port does not silently select another port', async () => {
  const { service, runtime, serial } = setup();
  serial.reconnect = async (port) => { assert.equal(port,'COM6'); throw new Error('COM6 not found'); };
  await service.recoverFpga();
  assert.equal(runtime.getState().serialConnected, false);
  assert.equal(runtime.getState().lastSerialPort, 'COM6');
  assert.match(service.useExperimentRun.getState().errorDetails, /COM6 not found/);
  assert.equal(runtime.getState().ad3Status, 'connected');
});
