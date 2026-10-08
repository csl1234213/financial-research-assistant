import assert from 'node:assert/strict';
import test from 'node:test';
import { translations } from '../src/i18n/translations.ts';
import { processingStageLabel } from '../src/i18n/processingCopy.ts';

function paths(value: unknown, prefix = ''): string[] {
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([key, child]) => paths(child, `${prefix}.${key}`));
  return [prefix];
}

test('both languages expose the same copy contract', () => {
  assert.deepEqual(paths(translations.en).sort(), paths(translations['zh-CN']).sort());
});

test('navigation uses everyday task names', () => {
  assert.equal(translations.en.app.nav.chat, 'Ask');
  assert.equal(translations['zh-CN'].app.nav.chat, '问答');
  assert.equal(translations['zh-CN'].app.nav.knowledge, '文档');
  assert.equal(translations['zh-CN'].app.nav.retrieval, '搜索');
});

test('indexed copy does not claim formal readiness', () => {
  assert.equal(translations.en.knowledge.indexed, 'Indexed');
  assert.equal(translations['zh-CN'].knowledge.indexed, '已收录');
});

test('processing labels translate all five stages without changing unknown states', () => {
  for (const stage of ['PARSING', 'QUALITY_CHECK', 'BUILDING_FACTS', 'BUILDING_TREE', 'INDEXING']) {
    assert.notEqual(processingStageLabel(stage, 'en'), stage);
    assert.notEqual(processingStageLabel(stage, 'zh-CN'), stage);
  }
  assert.equal(processingStageLabel('READY', 'en'), 'READY');
  assert.equal(processingStageLabel('UNKNOWN_STAGE', 'zh-CN'), 'UNKNOWN_STAGE');
});
