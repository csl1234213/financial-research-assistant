import type { Language } from '../types/language';

const stages: Record<string, Record<Language, string>> = {
  PARSING: { en: 'Reading Document', 'zh-CN': '读取文档' },
  QUALITY_CHECK: { en: 'Checking Content', 'zh-CN': '检查内容' },
  BUILDING_FACTS: { en: 'Organizing Data', 'zh-CN': '整理数据' },
  BUILDING_TREE: { en: 'Organizing Sections', 'zh-CN': '整理章节' },
  INDEXING: { en: 'Preparing Search', 'zh-CN': '准备搜索' },
};

/** Display-only labels: backend readiness and stage values stay unchanged. */
export function processingStageLabel(stage: string, language: Language): string {
  return stages[stage]?.[language] ?? stage;
}
