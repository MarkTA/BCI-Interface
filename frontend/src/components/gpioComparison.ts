/** Compare cyclic GPIO state *order*, not hardware edge timing.
 *
 * The FPGA sends AA 03 NN PP as UART packets without timestamps. USB latency
 * means host receive time is not a valid waveform time axis. This helper
 * aligns a recent complete cycle by an unambiguous comparator-state anchor.
 * We count bit transitions per channel across the cycle, including wrap.
 * A UART report can combine several simultaneous/rapid threshold crossings;
 * missing intermediate masks are therefore not necessarily missed bit edges.
 */
export type ReferenceState = { sample_index: number; mask: number };
export type GpioReport = [number, number]; // negative nibble, positive nibble
export const GPIO_CHANNELS = ["N1", "N2", "N3", "N4", "P1", "P2", "P3", "P4"] as const;

export type CycleMatch = {
  expected: number[];
  actual: number[];
  anchor: number;
  matchedStates: number;
  expectedEdges: number[];
  actualEdges: number[];
  endReportIndex: number;
};

const popcount = (v: number) => {
  let count = 0;
  for (let bit = 0; bit < 8; bit++) count += (v >> bit) & 1;
  return count;
};

export function cycleEdgeCounts(states: number[]): number[] {
  const counts = Array(8).fill(0) as number[];
  if (states.length < 2) return counts;
  for (let i = 0; i < states.length; i++) {
    const delta = states[i] ^ states[(i + 1) % states.length];
    for (let bit = 0; bit < 8; bit++) counts[bit] += (delta >> bit) & 1;
  }
  return counts;
}

export function longestOrderedMatch(expected: number[], observed: number[]): number {
  // Standard LCS; use memory O(observed.length). Small per-cycle sequences only.
  const previous = Array(observed.length + 1).fill(0) as number[];
  for (const item of expected) {
    let diagonal = 0;
    for (let j = 1; j <= observed.length; j++) {
      const before = previous[j];
      previous[j] = item === observed[j - 1]
        ? diagonal + 1
        : Math.max(previous[j], previous[j - 1]);
      diagonal = before;
    }
  }
  return previous[observed.length];
}

export function compareGpioCycle(
  referenceStates: ReferenceState[], reports: GpioReport[],
): CycleMatch | null {
  const expected = referenceStates.map((x) => x.mask);
  if (expected.length < 2 || expected.length > 128 || reports.length < 4) return null;
  // Collapse consecutive repeated packets; keep source packet indices so we can
  // locate the most recent identifiable cycle, not handpick the best cycle.
  const observed: { mask: number; index: number }[] = [];
  for (let i = 0; i < reports.length; i++) {
    const [n, p] = reports[i];
    if (!Number.isInteger(n) || !Number.isInteger(p) || n < 0 || p < 0 || n > 15 || p > 15) continue;
    const mask = n | (p << 4);
    if (observed.at(-1)?.mask !== mask) observed.push({ mask, index: i });
  }
  if (observed.length < 4) return null;

  // A state used once per reference cycle is an unambiguous phase marker.
  // Prefer strong threshold excursions (e.g. N=1111, P=1111), avoiding 0000,
  // which often occurs more than once per neural waveform cycle.
  const anchors = [...new Set(expected)]
    .filter((mask) => mask !== 0 && expected.filter((x) => x === mask).length === 1)
    .sort((a, b) => popcount(b) - popcount(a));

  let best: CycleMatch | null = null;
  for (const anchor of anchors) {
    const anchorIndex = expected.indexOf(anchor);
    const rotated = expected.slice(anchorIndex).concat(expected.slice(0, anchorIndex));
    const hits: number[] = [];
    for (let i = 0; i < observed.length; i++) {
      if (observed[i].mask === anchor) hits.push(i);
    }
    // Latest two *occurrences* of each marker yield one cycle. Avoid selecting
    // multiple cycles if the anchor gets skipped; reject wildly long windows.
    if (hits.length < 2) continue;
    const begin = hits[hits.length - 2];
    const end = hits[hits.length - 1];
    const actual = observed.slice(begin, end).map((item) => item.mask);
    if (actual.length < 3 || actual.length > rotated.length * 3) continue;
    const candidate: CycleMatch = {
      expected: rotated,
      actual,
      anchor,
      matchedStates: longestOrderedMatch(rotated, actual),
      expectedEdges: cycleEdgeCounts(rotated),
      actualEdges: cycleEdgeCounts(actual),
      endReportIndex: observed[end].index,
    };
    if (!best || candidate.endReportIndex > best.endReportIndex ||
        (candidate.endReportIndex === best.endReportIndex &&
         candidate.matchedStates > best.matchedStates)) best = candidate;
  }
  return best;
}
