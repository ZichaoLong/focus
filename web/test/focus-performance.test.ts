import { describe, expect, it } from 'vitest';
import { focusPerformance } from '../src/focus/focusPerformance';

describe('default-off performance evidence', () => {
  it('bounds records, freezes on stop and clears when restarted', () => {
    focusPerformance.stop();
    focusPerformance.record('socket_close', { code: 1006 });
    expect(focusPerformance.samples.value).toEqual([]);
    focusPerformance.start();
    for (let i = 0; i < 1000; i++) focusPerformance.record('event', { bytes: i });
    expect(focusPerformance.samples.value).toHaveLength(64);
    expect(focusPerformance.samples.value[0]?.bytes).toBe(936);
    focusPerformance.stop();
    focusPerformance.record('transcript_overflow', { bytes: 10000 });
    expect(focusPerformance.samples.value.at(-1)?.bytes).toBe(999);
    focusPerformance.start();
    expect(focusPerformance.samples.value).toEqual([]);
    focusPerformance.stop();
  });
});
