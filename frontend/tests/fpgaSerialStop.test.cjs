// Mock the actual WebSocket boundary; a stopped reply is a logical cleanup ACK.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function setup() {
  let ws;
  const state = {
    serialConnected: false, serialMock: false, runActive: false,
    setSerial(connected) { this.serialConnected = connected; },
    setRunActive(active) { this.runActive = active; },
    recordingStopped() {}, addLog() {},
  };
  state.setSerial = state.setSerial.bind(state);
  state.setRunActive = state.setRunActive.bind(state);
  class Socket {
    static OPEN = 1;
    readyState = 1;
    sent = [];
    constructor(url) { ws = this; this.url = url; }
    send(raw) { this.sent.push(JSON.parse(raw)); }
    close() { this.readyState = 3; this.onclose?.(); }
    receive(packet) { this.onmessage({ data: JSON.stringify(packet) }); }
  }
  const filename = path.join(__dirname, '../src/services/fpgaSerial.ts');
  const js = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {};
  vm.runInNewContext(js, { exports, require: () => ({ useRuntime: { getState: () => state } }), WebSocket: Socket, URLSearchParams, setTimeout, clearTimeout });
  const serial = exports.fpgaSerial;
  serial.connect('COM6', 115200, false);
  ws.receive({ type: 'status', message: 'Connected' });
  return { serial, ws, state, currentSocket: () => ws };
}
test('Stop awaits actual server reply even when local runActive is already false', async () => {
  const { serial, ws, state } = setup();
  let settled = false;
  const stopped = serial.stopRun().then(errors => { settled = true; return errors; });
  await Promise.resolve();
  assert.equal(settled, false);
  assert.equal(ws.sent.at(-1).active, false);
  ws.receive({ type: 'run_state', data: 'stopped', errors: ['AD3 recovery required'] });
  assert.equal((await stopped)[0], 'AD3 recovery required');
  assert.equal(state.serialConnected, true);
  assert.equal(state.runActive, false);
});
test('actual socket closure rejects pending Stop', async () => {
  const { serial, ws, state } = setup();
  const stopped = serial.stopRun();
  ws.close();
  await assert.rejects(stopped, /Serial connection closed/);
  assert.equal(state.serialConnected, false);
});


test('USB reader fault closes stale socket and rejects pending arm', async () => {
  const { serial, ws, state } = setup();
  const armed = serial.armRun(false);
  ws.receive({ type: 'serial_fault', message: 'Serial read failed: USB unplugged' });
  await assert.rejects(armed, /Serial connection disconnected/);
  assert.equal(serial.active, false);
  assert.equal(state.serialConnected, false);
});

test('reopen waits for bridge status and uses same port and baud', async () => {
  const { serial, ws, state, currentSocket } = setup();
  ws.receive({ type: 'serial_fault', message: 'USB unplugged' });
  let confirmed = false;
  const promise = serial.reconnect('COM6',115200).then(() => { confirmed = true; });
  await Promise.resolve();
  assert.equal(confirmed, false);
  assert.match(currentSocket().url, /port=COM6&baud=115200/);
  currentSocket().receive({ type: 'status' });
  await promise;
  assert.equal(state.serialConnected, true);
});

test('port open error rejects reconnect with actual reason', async () => {
  const { serial, ws, currentSocket } = setup();
  ws.close();
  const promise = serial.reconnect('COM6',115200);
  currentSocket().receive({ type: 'error', message: 'COM6 not found' });
  await assert.rejects(promise, /COM6 not found/);
  assert.equal(serial.active, false);
});
