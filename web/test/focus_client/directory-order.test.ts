import { describe, expect, it } from 'vitest';
import { useFocusWebClient } from '../../src/focus/useFocusWebClient';
import { FakeApi, installFocusClientTestHooks, snapshot, thread } from './support';

installFocusClientTestHooks();

function directory(client: ReturnType<typeof useFocusWebClient>) {
  return client.workspaceGroups.value.map((group) => ({
    root: group.workspace.root,
    threads: group.sessions.map((session) => session.id),
  }));
}

describe('Focus workspace and thread order', () => {
  it('keeps workspaces in place when selecting a thread refreshes its update time', async () => {
    const api = new FakeApi();
    const alpha = { ...thread(), id: 'alpha', cwd: '/work/alpha', updated_at: 30 };
    const betaOld = { ...thread(), id: 'beta-old', cwd: '/work/beta', updated_at: 10 };
    const betaNew = { ...thread(), id: 'beta-new', cwd: '/work/beta', updated_at: 20 };
    api.threads = [betaOld, alpha, betaNew];
    api.setSelectedThreadId(alpha.id);
    api.currentSnapshot = { ...snapshot('none', alpha.id), thread: alpha };
    const client = useFocusWebClient(api);
    await client.load();

    expect(directory(client)).toEqual([
      { root: '/work/alpha', threads: ['alpha'] },
      { root: '/work/beta', threads: ['beta-new', 'beta-old'] },
    ]);

    const refreshedBeta = { ...betaOld, updated_at: 40 };
    api.currentSnapshot = { ...snapshot('none', betaOld.id), thread: refreshedBeta };
    await client.selectThread(betaOld.id);

    const expected = [
      { root: '/work/alpha', threads: ['alpha'] },
      { root: '/work/beta', threads: ['beta-old', 'beta-new'] },
    ];
    expect(client.activeThreadId.value).toBe(betaOld.id);
    expect(directory(client)).toEqual(expected);

    api.threads = [betaNew, refreshedBeta, alpha];
    await client.reloadAll();
    expect(directory(client)).toEqual(expected);
    expect(api.threads.map((item) => item.id)).toEqual(['beta-new', 'beta-old', 'alpha']);
    client.dispose();

    const reloadedClient = useFocusWebClient(api);
    await reloadedClient.load();
    expect(directory(reloadedClient)).toEqual(expected);
    reloadedClient.dispose();
  });

  it('uses full paths and thread IDs to keep equal-name and equal-time entries stable', async () => {
    const api = new FakeApi();
    const alpha = { ...thread(), id: 'alpha', cwd: '/a/project', updated_at: 0 };
    const beta = { ...thread(), id: 'beta', cwd: '/a/project', updated_at: 0 };
    const zeta = { ...thread(), id: 'zeta', cwd: '/z/project', updated_at: 100 };
    api.threads = [zeta, beta, alpha];
    api.setDraftProfile('/a/project');
    const client = useFocusWebClient(api);
    await client.load();

    const expected = [
      { root: '/a/project', threads: ['alpha', 'beta'] },
      { root: '/z/project', threads: ['zeta'] },
    ];
    expect(directory(client)).toEqual(expected);

    api.threads = [alpha, beta, zeta];
    await client.setThreadScope('global');
    expect(directory(client)).toEqual(expected);

    const middle = { ...thread(), id: 'middle', cwd: '/m/project', updated_at: 200 };
    api.threads = [middle, zeta, beta, alpha];
    await client.reloadAll();
    expect(directory(client)).toEqual([
      expected[0],
      { root: '/m/project', threads: ['middle'] },
      expected[1],
    ]);

    api.threads = [beta, alpha];
    await client.setThreadScope('current');
    expect(directory(client)).toEqual([expected[0]]);
    client.dispose();
  });
});
