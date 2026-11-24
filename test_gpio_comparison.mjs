import assert from 'node:assert/strict';
import { compareGpioCycle, cycleEdgeCounts, longestOrderedMatch } from './frontend/src/components/gpioComparison.ts';

// Ideal negative-first polarity sequence; masks are N1..N4 in bits 0..3,
// P1..P4 in bits 4..7. Repeated 0 is NOT suitable as a phase anchor.
const states = [0, 1, 3, 7, 15, 7, 3, 1, 0, 16, 48, 112, 240, 112, 48, 16, 0];
const reference = states.map((mask, sample_index) => ({ mask, sample_index }));
assert.deepEqual(cycleEdgeCounts(states), [2, 2, 2, 2, 2, 2, 2, 2]);
assert.equal(longestOrderedMatch([0, 1, 3], [0, 3]), 2);

// UART may collapse brief intermediate comparator states into one GPIO packet,
// even while all bit transitions are preserved in the combined state change.
const collapsed = [0, 7, 15, 7, 0, 112, 240, 112, 0];
const combined = [...collapsed, ...collapsed, ...collapsed];
const reports = combined.map((mask) => [mask & 15, (mask >> 4) & 15]);
const match = compareGpioCycle(reference, reports);
assert.ok(match, 'expected a complete cycle');
assert.deepEqual(match.expectedEdges, [2, 2, 2, 2, 2, 2, 2, 2]);
assert.deepEqual(match.actualEdges, [2, 2, 2, 2, 2, 2, 2, 2]);
assert.ok(match.matchedStates < match.expected.length, 'should report merged intermediate masks');
assert.ok([15, 240].includes(match.anchor), 'should align using an unambiguous peak');

// An actually missing P4 transition shows up as the wrong channel's edge count.
const broken = [0, 7, 15, 7, 0, 112, 112, 0];
const brokenMatch = compareGpioCycle(reference, [...broken, ...broken, ...broken].map(m => [m & 15, m >> 4]));
assert.ok(brokenMatch);
assert.equal(brokenMatch.actualEdges[7], 0);
assert.equal(brokenMatch.expectedEdges[7], 2);

assert.equal(compareGpioCycle([{ sample_index: 0, mask: 0 }], [[0, 0], [0, 0]]), null);
assert.equal(compareGpioCycle(reference, []), null);
console.log('PASS: cyclic state comparison, collapsed UART states, incorrect channel, idle/no data');
