/** Versioned server-rendered views; never reconstruct exact facts from rounded prose. */
export interface FinancialPresentation {
  schema_version: 'financial-presentation.v1';
  exact_value: string;
  rendered: { 'zh-CN': string; en: string };
}

export function parseFinancialPresentation(value: unknown): FinancialPresentation | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.schema_version !== 'financial-presentation.v1') return null;
  if (typeof record.exact_value !== 'string'
    || !/^-?\d+(?:\.\d+)?$/.test(record.exact_value)
    || record.exact_value.length > 100) return null;
  for (const field of ['fact_id', 'canonical_metric', 'company', 'scope',
    'period_type', 'currency', 'unit', 'document_id', 'document_version']) {
    if (typeof record[field] !== 'string' || !record[field]) return null;
  }
  if (!Number.isInteger(record.page) || (record.page as number) < 1
    || record.citation_rank !== 1) return null;
  const rendered = record.rendered as Record<string, unknown> | null;
  if (!rendered || typeof rendered !== 'object') return null;
  if (typeof rendered['zh-CN'] !== 'string' || !rendered['zh-CN']
    || typeof rendered.en !== 'string' || !rendered.en
    || rendered.en.length > 10000 || rendered['zh-CN'].length > 10000) return null;
  return {
    schema_version: 'financial-presentation.v1',
    exact_value: record.exact_value,
    rendered: { 'zh-CN': rendered['zh-CN'], en: rendered.en },
  };
}
