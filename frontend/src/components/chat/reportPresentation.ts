import type { Language } from '../../types/language';

export type MarkdownBlock =
  | { type: 'heading'; level: 1 | 2 | 3 | 4; text: string }
  | { type: 'label'; text: string }
  | { type: 'paragraph'; text: string }
  | { type: 'table'; headers?: string[]; rows: string[][] }
  | { type: 'unordered-list'; items: string[] }
  | { type: 'ordered-list'; items: string[] }
  | { type: 'blockquote'; text: string }
  | { type: 'horizontal-rule' };

export interface ResearchReportParts {
  question: string;
  modelAnswer: string;
  evidenceUsed: string;
  agentAnalysis: string;
}

export interface ModelIdentity {
  provider: string;
  model: string | null;
}

export type RuntimeFailureKind =
  | 'provider-disabled'
  | 'provider-configuration'
  | 'provider-error'
  | 'agent-runtime-fallback';

/** Classifies backend fallback markers so the UI never presents them as an AI answer. */
export function getRuntimeFailureKind(report: string): RuntimeFailureKind | null {
  if (report.startsWith('[Provider Disabled]')) return 'provider-disabled';
  if (report.startsWith('[Provider Configuration Error]')) return 'provider-configuration';
  if (report.startsWith('[Provider Error]')) return 'provider-error';
  if (report.startsWith('[Agent Runtime Fallback]')) return 'agent-runtime-fallback';
  return null;
}

export function shouldShowAnswerDisclaimer(report: string): boolean {
  return getRuntimeFailureKind(report) === null;
}

/** Render explicit CNY amounts in Chinese monetary units without changing evidence data. */
export function localizeCnyAmounts(answer: string, language: Language): string {
  if (!answer) return answer;

  const formatYuan = (yuan: number): string => {
    const absoluteYuan = Math.abs(yuan);
    if (language === 'en') {
      const unit = absoluteYuan >= 1_000_000_000
        ? { divisor: 1_000_000_000, label: 'billion' }
        : absoluteYuan >= 1_000_000
          ? { divisor: 1_000_000, label: 'million' }
          : absoluteYuan >= 1_000
            ? { divisor: 1_000, label: 'thousand' }
            : { divisor: 1, label: '' };
      const formattedEnglish = new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(yuan / unit.divisor);
      return `CNY ${formattedEnglish}${unit.label ? ` ${unit.label}` : ''}`;
    }

    const unit = absoluteYuan >= 100_000_000
      ? { divisor: 100_000_000, label: '亿元人民币' }
      : absoluteYuan >= 10_000
        ? { divisor: 10_000, label: '万元人民币' }
        : { divisor: 1, label: '元人民币' };
    const formattedChinese = new Intl.NumberFormat('zh-CN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(yuan / unit.divisor);
    return `${formattedChinese} ${unit.label}`;
  };

  // Some answers are already rendered in Chinese yuan units by a model or a
  // deterministic fact-ledger fallback. Normalize them for the selected UI.
  const chineseAmountPattern = /(?<![\p{L}\d])([+-]?[\d,]+(?:\.\d+)?)\s*(亿元人民币|万元人民币|元人民币)(?![\p{L}\d])/gu;
  let localized = answer.replace(
    chineseAmountPattern,
    (match, amountText: string, unit: string) => {
      // Scaled prose may already be rounded. It is not an exact source observation.
      if (unit !== '元人民币') return match;
      const amount = Number(amountText.replaceAll(',', ''));
      if (!Number.isFinite(amount)) return match;
      return formatYuan(amount);
    },
  );

  const amountPattern = /(?<![\p{L}\d])(?:(CNY|RMB)\s*([+-]?[\d,]+(?:\.\d+)?)\s*(billion|million|thousand)?|([+-]?[\d,]+(?:\.\d+)?)\s*(billion|million|thousand)\s*(CNY|RMB)|([+-]?[\d,]+(?:\.\d+)?)\s*(CNY|RMB))(?![\p{L}\d])/giu;
  localized = localized.replace(amountPattern, (match, prefixCurrency: string | undefined, prefixAmount: string | undefined, prefixScale: string | undefined, suffixAmount: string | undefined, suffixScale: string | undefined, suffixCurrency: string | undefined, plainAmount: string | undefined) => {
    const amountText = prefixAmount ?? suffixAmount ?? plainAmount;
    if (!amountText) return match;

    const amount = Number(amountText.replaceAll(',', ''));
    if (!Number.isFinite(amount)) return match;

    const scale = (prefixScale ?? suffixScale ?? '').toLowerCase();
    if (scale) return match;
    const multiplier = scale === 'billion'
      ? 1_000_000_000
      : scale === 'million'
        ? 1_000_000
        : scale === 'thousand'
          ? 1_000
          : 1;
    const yuan = amount * multiplier;
    // Currency groups are parsed explicitly to avoid localizing bare figures,
    // financial-year labels, or USD values.
    void prefixCurrency;
    void suffixCurrency;
    return formatYuan(yuan);
  });

  return language === 'zh-CN'
    ? localized.replace(/\bFY\s*(20\d{2})\b/gi, '$1财年')
    : localized;
}

const modelSectionLabels = new Set([
  'summary',
  'key findings',
  'risks',
  'evidence used',
  '摘要',
  '主要发现',
  '风险',
  '使用的证据',
]);

const agentSectionHeadings = new Set([
  'key facts',
  'risk signals',
  'opportunity signals',
  'ai conclusion',
  'source coverage',
  '关键事实',
  '风险信号',
  '机会信号',
  'ai 结论',
  '来源覆盖',
]);

const reportTitleHeadings = new Set(['research report', '研究报告']);
const questionHeadings = new Set(['question', '问题']);
const answerHeadings = new Set([
  'answer',
  'answer (llm answer)',
  '回答',
  '回答（llm 模型回答）',
]);
const agentBoundaryHeadings = new Set([
  'agent evidence analysis',
  '智能体证据分析',
]);
const evidenceUsedHeadings = new Set([
  'evidence used',
  '使用的证据',
  '引用证据',
]);

const chineseReportHeadings = new Map([
  ['summary', '摘要'],
  ['key findings', '关键发现'],
  ['risks', '风险'],
  ['evidence used', '使用的证据'],
]);

export function localizeReportHeading(
  heading: string,
  language: Language,
): string {
  if (language !== 'zh-CN') return heading;
  return chineseReportHeadings.get(heading.trim().toLowerCase()) ?? heading;
}

function isBlockStart(line: string): boolean {
  const trimmed = line.trim();
  return (
    /^#{1,4}\s+\S/.test(trimmed)
    || /^[-*+]\s+\S/.test(trimmed)
    || /^\d+[.)]\s+\S/.test(trimmed)
    || /^>\s?/.test(trimmed)
    || /^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)
    || modelSectionLabels.has(trimmed.toLowerCase())
  );
}

function splitMarkdownTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes('|')) return null;

  const source = trimmed
    .replace(/^\|/, '')
    .replace(/(?<!\\)\|$/, '');
  const cells: string[] = [];
  let cell = '';
  let escaped = false;

  for (const character of source) {
    if (escaped) {
      cell += character;
      escaped = false;
    } else if (character === '\\') {
      escaped = true;
    } else if (character === '|') {
      cells.push(cell.trim());
      cell = '';
    } else {
      cell += character;
    }
  }

  if (escaped) cell += '\\';
  cells.push(cell.trim());
  return cells;
}

function isMarkdownTableSeparator(cells: string[]): boolean {
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function isMarkdownTableStart(lines: string[], index: number): boolean {
  if (index + 1 >= lines.length) return false;
  const headers = splitMarkdownTableRow(lines[index]);
  const separator = splitMarkdownTableRow(lines[index + 1]);
  return Boolean(
    headers
    && separator
    && headers.length === separator.length
    && isMarkdownTableSeparator(separator),
  );
}

function isHeaderlessPipeTableStart(lines: string[], index: number): boolean {
  const first = splitMarkdownTableRow(lines[index]);
  if (!first || first.length < 2 || !lines[index].trim().startsWith('|')) return false;

  let rowCount = 1;
  for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
    const row = splitMarkdownTableRow(lines[cursor]);
    if (!row || !lines[cursor].trim().startsWith('|') || row.length !== first.length) break;
    if (isMarkdownTableSeparator(row)) break;
    rowCount += 1;
  }

  // Only promote a repeated, rectangular block of pipe-delimited rows.
  // A single inline pipe or an irregular list remains ordinary text.
  return rowCount >= 2;
}

/**
 * Parses a deliberately small Markdown subset. Raw HTML has no special block
 * type and remains ordinary text so React will escape it during rendering.
 */
export function parseRestrictedMarkdown(markdown: string): MarkdownBlock[] {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const trimmed = lines[index].trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (isMarkdownTableStart(lines, index)) {
      const tableHeaders = splitMarkdownTableRow(lines[index]);
      if (!tableHeaders) continue;
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length) {
        const row = splitMarkdownTableRow(lines[index]);
        if (!row || row.length !== tableHeaders.length) break;
        rows.push(row);
        index += 1;
      }
      blocks.push({ type: 'table', headers: tableHeaders, rows });
      continue;
    }

    if (isHeaderlessPipeTableStart(lines, index)) {
      const firstRow = splitMarkdownTableRow(lines[index]);
      if (!firstRow) continue;
      const rows: string[][] = [];
      while (index < lines.length) {
        const row = splitMarkdownTableRow(lines[index]);
        if (!row || !lines[index].trim().startsWith('|') || row.length !== firstRow.length) break;
        rows.push(row);
        index += 1;
      }
      blocks.push({ type: 'table', rows });
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (heading) {
      blocks.push({
        type: 'heading',
        level: heading[1].length as 1 | 2 | 3 | 4,
        text: heading[2].trim(),
      });
      index += 1;
      continue;
    }

    if (modelSectionLabels.has(trimmed.toLowerCase())) {
      blocks.push({ type: 'label', text: trimmed });
      index += 1;
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push({ type: 'horizontal-rule' });
      index += 1;
      continue;
    }

    if (/^[-*+]\s+\S/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = /^[-*+]\s+(.+)$/.exec(lines[index].trim());
        if (!match) break;
        items.push(match[1].trim());
        index += 1;
      }
      blocks.push({ type: 'unordered-list', items });
      continue;
    }

    if (/^\d+[.)]\s+\S/.test(trimmed)) {
      const items: string[] = [];
      while (index < lines.length) {
        const match = /^\d+[.)]\s+(.+)$/.exec(lines[index].trim());
        if (!match) break;
        items.push(match[1].trim());
        index += 1;
      }
      blocks.push({ type: 'ordered-list', items });
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = [];
      while (index < lines.length) {
        const match = /^>\s?(.*)$/.exec(lines[index].trim());
        if (!match) break;
        quoteLines.push(match[1]);
        index += 1;
      }
      blocks.push({ type: 'blockquote', text: quoteLines.join('\n') });
      continue;
    }

    const paragraphLines = [lines[index].trim()];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !isBlockStart(lines[index])
      && !isMarkdownTableStart(lines, index)
      && !isHeaderlessPipeTableStart(lines, index)
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: 'paragraph', text: paragraphLines.join('\n') });
  }

  return blocks;
}

function findMarkdownHeadingIndex(
  lines: string[],
  headings: Set<string>,
  minimumLevel: number,
  start = 0,
): number {
  return lines.findIndex((line, index) => {
    if (index < start) return false;
    const match = /^(#{1,6})\s+(.+)$/.exec(line.trim());
    return Boolean(
      match
      && match[1].length >= minimumLevel
      && headings.has(match[2].trim().toLowerCase()),
    );
  });
}

/**
 * Separates the provider-generated answer from the deterministic evidence
 * analysis appended by the Agent Runtime report builder.
 */
export function splitResearchReport(
  report: string,
): ResearchReportParts | null {
  const lines = report.replace(/\r\n?/g, '\n').split('\n');
  const reportTitleIndex = findMarkdownHeadingIndex(lines, reportTitleHeadings, 1);
  if (reportTitleIndex < 0) return null;

  const answerIndex = findMarkdownHeadingIndex(
    lines,
    answerHeadings,
    2,
    reportTitleIndex,
  );
  if (answerIndex < 0) return null;

  const questionIndex = findMarkdownHeadingIndex(
    lines,
    questionHeadings,
    2,
    reportTitleIndex,
  );
  const explicitAgentBoundaryIndex = findMarkdownHeadingIndex(
    lines,
    agentBoundaryHeadings,
    2,
    answerIndex + 1,
  );
  const legacyAgentStartIndex = lines.findIndex((line, index) => {
    if (index <= answerIndex) return false;
    const match = /^#{2,6}\s+(.+)$/.exec(line.trim());
    return Boolean(
      match
      && agentSectionHeadings.has(match[1].trim().toLowerCase()),
    );
  });
  const agentStartIndex = explicitAgentBoundaryIndex >= 0
    ? explicitAgentBoundaryIndex
    : legacyAgentStartIndex;
  const agentContentStartIndex = explicitAgentBoundaryIndex >= 0
    ? explicitAgentBoundaryIndex + 1
    : agentStartIndex;

  const modelEndIndex = agentStartIndex >= 0 ? agentStartIndex : lines.length;
  const evidenceUsedIndex = lines.findIndex((line, index) => {
    if (index <= answerIndex || index >= modelEndIndex) return false;
    const normalized = line
      .trim()
      .replace(/^#{1,6}\s+/, '')
      .trim()
      .toLowerCase();
    return evidenceUsedHeadings.has(normalized);
  });
  const modelContentEndIndex = evidenceUsedIndex >= 0
    ? evidenceUsedIndex
    : modelEndIndex;
  const question = questionIndex >= 0 && questionIndex < answerIndex
    ? lines.slice(questionIndex + 1, answerIndex).join('\n').trim()
    : '';
  const modelAnswer = lines
    .slice(answerIndex + 1, modelContentEndIndex)
    .join('\n')
    .trim();
  const evidenceUsed = evidenceUsedIndex >= 0
    ? lines.slice(evidenceUsedIndex + 1, modelEndIndex).join('\n').trim()
    : '';
  const agentAnalysis = agentStartIndex >= 0
    ? lines.slice(agentContentStartIndex).join('\n').trim()
    : '';

  if (!modelAnswer) return null;
  return {
    question,
    modelAnswer,
    evidenceUsed,
    agentAnalysis,
  };
}

export function extractModelIdentity(
  routing: Record<string, unknown> | null | undefined,
): ModelIdentity | null {
  const provider = routing?.provider;
  if (typeof provider !== 'string' || !provider.trim()) return null;

  const model = routing?.model;
  return {
    provider: provider.trim(),
    model: typeof model === 'string' && model.trim() ? model.trim() : null,
  };
}

export function buildCitationDomId(
  namespace: string,
  evidenceNumber: number,
): string {
  const safeNamespace = namespace
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'chat-turn';
  const safeNumber = Number.isInteger(evidenceNumber) && evidenceNumber > 0
    ? evidenceNumber
    : 1;
  return `${safeNamespace}-evidence-${safeNumber}`;
}
