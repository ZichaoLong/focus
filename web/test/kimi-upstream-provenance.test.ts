import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import {
  assertRelativePath,
  readUpstreamRegularFile,
} from '../scripts/kimi-upstream-provenance.mjs';

const temporaryRoots: string[] = [];

function git(root: string, args: string[]): string {
  return execFileSync('git', ['-C', root, ...args], { encoding: 'utf8' }).trim();
}

function upstreamFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'focus-kimi-provenance-'));
  temporaryRoots.push(root);
  git(root, ['init', '-q']);
  git(root, ['config', 'user.name', 'Focus Test']);
  git(root, ['config', 'user.email', 'focus@example.invalid']);
  const sourceRoot = path.join(root, 'apps', 'kimi-web');
  fs.mkdirSync(path.join(sourceRoot, 'directory'), { recursive: true });
  fs.writeFileSync(path.join(sourceRoot, 'file.txt'), 'source\n', 'utf8');
  fs.writeFileSync(path.join(sourceRoot, 'directory', 'nested.txt'), 'nested\n', 'utf8');
  git(root, ['add', '.']);
  const linkObject = execFileSync(
    'git',
    ['-C', root, 'hash-object', '-w', '--stdin'],
    { encoding: 'utf8', input: 'file.txt' },
  ).trim();
  git(root, [
    'update-index',
    '--add',
    '--cacheinfo',
    '120000',
    linkObject,
    'apps/kimi-web/link.txt',
  ]);
  git(root, ['commit', '-q', '-m', 'fixture']);
  return {
    root,
    upstream: {
      imported_commit: git(root, ['rev-parse', 'HEAD']),
      source_root: 'apps/kimi-web',
    },
  };
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) fs.rmSync(root, { recursive: true });
});

describe('Kimi upstream provenance guard', () => {
  it('rejects parent and control-character paths', () => {
    for (const unsafe of ['..', '../file', 'a/../file', 'line\nbreak']) {
      expect(() => assertRelativePath(unsafe, 'fixture')).toThrow(/safe POSIX-relative path/u);
    }
  });

  it('reads only exact regular blobs from the recorded source tree', () => {
    const { root, upstream } = upstreamFixture();
    expect(readUpstreamRegularFile(upstream, root, 'file.txt', 'fixture').toString('utf8'))
      .toBe('source\n');
    expect(() => readUpstreamRegularFile(upstream, root, 'directory', 'fixture'))
      .toThrow(/not a regular Git file/u);
    expect(() => readUpstreamRegularFile(upstream, root, 'link.txt', 'fixture'))
      .toThrow(/not a regular Git file/u);
  });
});
