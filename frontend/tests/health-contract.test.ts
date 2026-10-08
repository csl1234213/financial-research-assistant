import assert from 'node:assert/strict';
import test from 'node:test';

import { parseHealthResponse } from '../src/api/healthContract.ts';

test('parses dependency health status without trusting arbitrary strings', () => {
  assert.deepEqual(parseHealthResponse({
    status: 'ok',
    version: '8.1.0',
    components: { database: 'up', redis: 'degraded' },
  }), {
    status: 'ok',
    version: '8.1.0',
    components: { database: 'up', redis: 'degraded' },
  });
  assert.throws(
    () => parseHealthResponse({ status: 'ready' }),
    /status is not supported/,
  );
});
