import assert from 'node:assert/strict';
import test from 'node:test';

import { clearPermissionCache, getPermission } from '../src/permission-cache.js';

test.beforeEach(() => clearPermissionCache());

test('reuses a cached permission decision', () => {
  let evaluations = 0;
  const context = { tenantId: 'north', userId: 'u1', documentId: 'doc1', roleVersion: 1 };
  const evaluate = () => {
    evaluations += 1;
    return true;
  };

  assert.equal(getPermission(context, evaluate), true);
  assert.equal(getPermission(context, evaluate), true);
  assert.equal(evaluations, 1);
});
