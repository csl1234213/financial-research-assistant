import assert from 'node:assert/strict';
import test from 'node:test';

import {
  parseAuthUser,
  parseLoginResponse,
  parseRegisterResponse,
} from '../src/api/authContract.ts';

test('parses the authenticated user contract', () => {
  assert.deepEqual(parseAuthUser({
    id: 7,
    email: 'tester@example.com',
    role: 'member',
    tenant: { id: 3, name: 'Evaluation', slug: 'evaluation' },
  }), {
    id: 7,
    email: 'tester@example.com',
    role: 'member',
    tenant: { id: 3, name: 'Evaluation', slug: 'evaluation' },
  });
  assert.deepEqual(parseAuthUser({
    id: 7,
    email: 'tester@example.com',
    role: 'member',
    tenant: null,
  }).tenant, null);
});

test('rejects malformed auth responses before storing tokens', () => {
  assert.throws(
    () => parseLoginResponse({ access_token: '', token_type: 'bearer' }),
    /access_token must be a non-empty string/,
  );
  assert.throws(
    () => parseRegisterResponse({ id: '7', email: 'tester@example.com', token: 'token' }),
    /id must be a non-negative integer/,
  );
});
