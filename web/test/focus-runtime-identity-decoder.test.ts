import { describe, expect, it } from 'vitest';
import { decodeFocusMeta } from '../src/focus/httpResponseDecoder';
import { meta } from './focus-api-test-support';


describe('Focus runtime identity decoder', () => {
  it('requires one exact installed build and app-server identity shape', () => {
    expect(decodeFocusMeta({ ...meta, runtime_identity: undefined })).toBeNull();
    expect(decodeFocusMeta({
      ...meta,
      runtime_identity: {
        ...meta.runtime_identity,
        installed_build: {
          ...meta.runtime_identity.installed_build,
          channel: 'nightly',
        },
      },
    })).toBeNull();
    expect(decodeFocusMeta({
      ...meta,
      runtime_identity: {
        ...meta.runtime_identity,
        installed_build: {
          ...meta.runtime_identity.installed_build,
          version: '4.9.0',
        },
      },
    })).toBeNull();
    expect(decodeFocusMeta({
      ...meta,
      runtime_identity: {
        ...meta.runtime_identity,
        codex_app_server: { user_agent: '  ' },
      },
    })).toBeNull();
  });
});
