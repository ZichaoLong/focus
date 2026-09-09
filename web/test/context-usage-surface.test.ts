import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const composer = readFileSync(
  fileURLToPath(new URL('../src/components/chat/Composer.vue', import.meta.url)),
  'utf8',
);

describe('Composer context usage surface', () => {
  it('hides an unavailable ring without gating permitted manual compact on usage', () => {
    expect(composer).toContain('v-if="status && !hideContext && hasContextUsage"');
    expect(composer).toContain(
      '<button v-if="capabilities.compact" class="compact-chip"',
    );
    expect(composer).not.toContain('showCompact');
    expect(composer).not.toContain('pct.value >= 80');
  });

  it('draws used percent from the projected remaining percent', () => {
    expect(composer).toContain('100 - (props.status?.ctxRemainingPct ?? 100)');
  });
});
