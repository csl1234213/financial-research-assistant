import assert from 'node:assert/strict';
import test from 'node:test';
import { createGroundedChatRequest } from '../src/api/groundedChatContract.ts';

test('grounded pilot binds job and locale without accepting client evidence', () => {
  const request = createGroundedChatRequest('job-1', '贵州茅台总资产是多少？', 'zh-CN', true);
  assert.deepEqual(request, {
    ingestion_job_id: 'job-1', question: '贵州茅台总资产是多少？', answer_language: 'zh-CN', stream: true,
  });
  assert.equal(createGroundedChatRequest('job-1', 'Total assets?', 'en').stream, false);
  for (const job of ['', ' ', 'x'.repeat(129)]) {
    assert.throws(() => createGroundedChatRequest(job, 'Assets?', 'en'));
  }
  for (const question of ['', ' ', 'x'.repeat(4001)]) {
    assert.throws(() => createGroundedChatRequest('job-1', question, 'en'));
  }
});
import { parseFinancialPresentation } from '../src/api/financialPresentationContract.ts';

test('versioned financial presentation preserves exact decimal and rejects unsafe metadata', () => {
  const payload = {
    schema_version: 'financial-presentation.v1', exact_value: '303834844021.44',
    fact_id: 'fact-1', canonical_metric: 'total_assets', company: '贵州茅台',
    scope: 'CONSOLIDATED', period_type: 'INSTANT', currency: 'CNY', unit: '元',
    document_id: 'report-1', document_version: 'hash-1', page: 57, citation_rank: 1,
    rendered: { 'zh-CN': '约人民币3038.35亿元 [1]', en: 'Approximately 303.83 billion CNY [1]' },
  };
  assert.equal(parseFinancialPresentation(payload)?.exact_value, '303834844021.44');
  for (const invalid of [null, {}, { ...payload, schema_version: 'v2' },
    { ...payload, exact_value: 303834844021.44 }, { ...payload, page: 0 },
    { ...payload, rendered: { en: 'only English' } }]) {
    assert.equal(parseFinancialPresentation(invalid), null);
  }
  const detail = (metadata: unknown) => parseConversationDetail({
    session: { thread_id: 't', message_count: 1, created_at: '', updated_at: '' },
    messages: [{ id: 1, role: 'assistant', content: 'legacy text', metadata }],
    total_messages: 1, limit: 500, offset: 0,
  }).messages[0];
  const citations = [{ rank: 1, source: 'report.pdf', chunk_id: 'c1', similarity: null, preview: 'evidence' }];
  const restored = detail({ financial_presentation: payload, citations });
  assert.equal(restored.financialPresentation?.rendered['zh-CN'], payload.rendered['zh-CN']);
  assert.equal(restored.financialPresentation?.rendered.en, payload.rendered.en);
  assert.equal(restored.savedCitations?.length, 1);
  assert.equal(detail({ financial_presentation: payload }).financialPresentation, null);
  assert.equal(detail({}).content, 'legacy text');
  const api = {
    ...currentBackendResponse(), citations,
    planning: { structured_financial_query: { financial_presentation: payload } },
    execution: { strategy: 'structured_financial_fact', status: 'FOUND', provider_calls: 0 },
    workflow: { type: 'structured_financial_fact', status: 'completed' },
  };
  assert.equal(parseChatResponse(api).financialPresentation?.exact_value, payload.exact_value);
  for (const status of ['CONFLICT', 'NOT_FOUND', 'AMBIGUOUS']) {
    assert.equal(parseChatResponse({ ...api, execution: { ...api.execution, status } }).financialPresentation, null);
  }
  assert.equal(parseChatResponse({ ...api, citations: [] }).financialPresentation, null);
});
import { isCompletedStructuredFact, isSafeStructuredRefusal } from '../src/components/agent/structuredExecution.ts';

test('safe refusal is distinct from system failure and fact success', () => {
  const response = {
    execution: { strategy: 'structured_financial_fact', status: 'UNSUPPORTED_METRIC', provider_calls: 0 },
    workflow: { type: 'structured_financial_fact', status: 'safe_failure' }, citations: [],
  } as unknown as ChatResponse;
  assert.equal(isSafeStructuredRefusal(response), true);
  assert.equal(isCompletedStructuredFact(response), false);
  for (const status of ['FOUND', 'ERROR', 'FAILED']) {
    assert.equal(isSafeStructuredRefusal({ ...response, execution: { ...response.execution!, status } }), false);
  }
  assert.equal(isSafeStructuredRefusal({ ...response, workflow: { type: 'rag', status: 'failed' } }), false);
  assert.equal(isSafeStructuredRefusal(null), false);
});
import type { ChatResponse } from '../src/types/api.ts';

test('structured success without provider routing is completed, not a provider failure', () => {
  const response = {
    execution: { strategy: 'structured_financial_fact', status: 'FOUND', provider_calls: 0 },
    workflow: { type: 'structured_financial_fact', status: 'completed' },
    citations: [{ rank: 1 }], routing: null,
  } as ChatResponse;
  assert.equal(isCompletedStructuredFact(response), true);
  assert.equal(isCompletedStructuredFact(null), false);
  for (const status of ['NOT_FOUND', 'CONFLICT', 'FAILED']) {
    assert.equal(isCompletedStructuredFact({ ...response, execution: { ...response.execution!, status } }), false);
  }
  assert.equal(isCompletedStructuredFact({ ...response, citations: [] }), false);
  assert.equal(isCompletedStructuredFact({ ...response, execution: { ...response.execution!, provider_calls: 1 } }), false);
  assert.equal(isCompletedStructuredFact({ ...response, workflow: { type: 'rag', status: 'completed' } }), false);
});
import { formatGenerationDuration } from '../src/components/chat/generationDuration.ts';

test('keeps generation duration localized and displays minutes and seconds', () => {
  assert.equal(formatGenerationDuration(18200, 'zh-CN'), '用时 18.2 秒');
  assert.equal(formatGenerationDuration(18200, 'en'), 'Generated in 18.2 s');
  assert.equal(formatGenerationDuration(62500, 'zh-CN'), '用时 1 分 2.5 秒');
  assert.equal(formatGenerationDuration(62500, 'en'), 'Generated in 1 min 2.5 s');
  assert.equal(formatGenerationDuration(59999, 'zh-CN'), '用时 1 分 0.0 秒');
  assert.equal(formatGenerationDuration(0, 'zh-CN'), '用时 0.0 秒');
});

test('does not invent elapsed time for history without duration metadata', () => {
  for (const value of [undefined, NaN, Infinity, -1]) {
    assert.equal(formatGenerationDuration(value, 'zh-CN'), null);
  }
});

import {
  ChatContractError,
  createChatRequest,
  parseChatResponse,
  parseCitation,
} from '../src/api/chatContract.ts';

test('grounded citation retains document identity and accepts the public locator contract', () => {
  const citation = { rank: 1, source: 'filing.pdf', chunk_id: 'fact-1', similarity: null,
    preview: '资产总计', page: 52, source_locator: 'table:balance-sheet:row:total-assets',
    document_id: '42', content_sha256: 'a'.repeat(64) };
  assert.deepEqual(parseCitation(citation, 0), citation);
  assert.throws(() => parseCitation({ ...citation, source_locator: { page: 52 } }, 0));
  assert.throws(() => parseCitation({ ...citation, content_sha256: 'not-a-digest' }, 0));
});
import {
  buildConversationDeletePath,
  buildConversationDetailPath,
  parseConversationDeleteResult,
  parseConversationDetail,
  parseConversationList,
} from '../src/api/agentSessionContract.ts';
import { buildApiUrl } from '../src/api/url.ts';
import {
  buildCitationDomId,
  extractModelIdentity,
  getRuntimeFailureKind,
  localizeCnyAmounts,
  localizeReportHeading,
  parseRestrictedMarkdown,
  shouldShowAnswerDisclaimer,
  splitResearchReport,
} from '../src/components/chat/reportPresentation.ts';

function currentBackendResponse(): Record<string, unknown> {
  return {
    report: 'Tesla revenue increased.',
    citations: [
      {
        rank: 1,
        source: 'Tesla_Q2_2025.pdf',
        chunk_id: 'tesla-q2-14',
        similarity: 0.93,
        preview: 'Revenue increased during the quarter.',
      },
    ],
    reasoning: {
      intent: 'SINGLE_COMPANY',
      companies: ['Tesla'],
      research_mode: 'default',
      evidence_count: 1,
    },
    plan: {
      intent: 'single_company',
      task_count: 1,
      tasks: [],
    },
    execution_time: 0.42,
    routing: {
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
    },
    planning: {
      task_type: 'document_qa',
    },
    execution: {
      strategy: 'rag',
      use_retrieval: true,
    },
    workflow: {
      type: 'rag',
      status: 'completed',
    },
  };
}

test('creates the backend request with question, never message', () => {
  assert.deepEqual(
    createChatRequest(
      '  Analyze Tesla revenue growth  ',
      ' Tesla ',
      ' chat-session-123 ',
    ),
    {
      question: 'Analyze Tesla revenue growth',
      company: 'Tesla',
      thread_id: 'chat-session-123',
    },
  );
});

test('sends the selected UI language as the requested answer language', () => {
  assert.deepEqual(
    createChatRequest('贵州茅台收入是多少？', undefined, undefined, 'en'),
    { question: '贵州茅台收入是多少？', answer_language: 'en' },
  );
  assert.deepEqual(
    createChatRequest('What is revenue?', undefined, undefined, 'zh-CN'),
    { question: 'What is revenue?', answer_language: 'zh-CN' },
  );
});

test('keeps thread id optional for non-interactive API callers', () => {
  assert.deepEqual(createChatRequest('What is AI?'), {
    question: 'What is AI?',
  });
});

test('classifies runtime failures without treating them as generated answers', () => {
  assert.equal(
    getRuntimeFailureKind('[Provider Disabled] External calls are blocked.'),
    'provider-disabled',
  );
  assert.equal(
    getRuntimeFailureKind('[Agent Runtime Fallback] Unable to process.'),
    'agent-runtime-fallback',
  );
  assert.equal(getRuntimeFailureKind('贵州茅台2025年营收为1688亿元。'), null);
  assert.equal(shouldShowAnswerDisclaimer('贵州茅台2025年营收为1688亿元。'), true);
  assert.equal(shouldShowAnswerDisclaimer('[Agent Runtime Fallback] No answer.'), false);
});

test('formats explicit CNY amounts using Chinese or English conventions', () => {
  const answer = '贵州茅台 FY2025 净利润: 82.32006710168 billion CNY [1].';
  assert.equal(
    localizeCnyAmounts(answer, 'zh-CN'),
    '贵州茅台 2025财年 净利润: 82.32006710168 billion CNY [1].',
  );
  assert.equal(
    localizeCnyAmounts('CNY 0.75 million [1]', 'zh-CN'),
    'CNY 0.75 million [1]',
  );
  assert.equal(
    localizeCnyAmounts('$82.32 billion USD', 'zh-CN'),
    '$82.32 billion USD',
  );
  assert.equal(
    localizeCnyAmounts(answer, 'en'),
    answer,
  );
  assert.equal(
    localizeCnyAmounts('CNY 0.75 million [1]', 'en'),
    'CNY 0.75 million [1]',
  );
  assert.equal(
    localizeCnyAmounts('FY2025 revenue: 168,838,102,514.79元人民币 [1]', 'zh-CN'),
    '2025财年 revenue: 1,688.38 亿元人民币 [1]',
  );
  assert.equal(
    localizeCnyAmounts('FY2025 revenue: 168,838,102,514.79元人民币 [1]', 'en'),
    'FY2025 revenue: CNY 168.84 billion [1]',
  );
});

test('never re-scales a rounded historical amount on language switching', () => {
  const english = 'approximately CNY 303.83 billion [1]';
  assert.equal(localizeCnyAmounts(english, 'zh-CN'), english);
  const chinese = '约人民币 3,038.35 亿元 [1]';
  assert.equal(localizeCnyAmounts(chinese, 'en'), chinese);
  assert.equal(localizeCnyAmounts('3,038.35 亿元人民币 [1]', 'en'), '3,038.35 亿元人民币 [1]');
  assert.equal(localizeCnyAmounts(localizeCnyAmounts(english, 'zh-CN'), 'en'), english);
});

test('builds the canonical Docker and Vite proxy chat URL', () => {
  assert.equal(buildApiUrl('/api', '/v1/chat'), '/api/v1/chat');
  assert.equal(
    buildApiUrl('http://localhost:8000/api/', 'v1/chat'),
    'http://localhost:8000/api/v1/chat',
  );
});

test('accepts the current backend citation and routing provider contract', () => {
  const response = parseChatResponse(currentBackendResponse());

  assert.equal(response.citations[0].source, 'Tesla_Q2_2025.pdf');
  assert.equal(response.citations[0].preview, 'Revenue increased during the quarter.');
  assert.equal(response.routing?.provider, 'deepseek');
  assert.equal(response.execution?.strategy, 'rag');
});

test('rejects the obsolete frontend-only citation shape', () => {
  const payload = currentBackendResponse();
  payload.citations = [
    {
      filename: 'Tesla_Q2_2025.pdf',
      page: 14,
      similarity: 0.93,
      snippet: 'Legacy UI shape.',
    },
  ];

  assert.throws(
    () => parseChatResponse(payload),
    (error: unknown) => (
      error instanceof ChatContractError
      && error.message.includes('citations[0].rank')
    ),
  );
});

test('rejects malformed typed reasoning and routing fields at the API boundary', () => {
  const reasoningPayload = currentBackendResponse();
  reasoningPayload.reasoning = {
    intent: 'SINGLE_COMPANY',
    companies: ['Tesla', 42],
    research_mode: 'default',
    evidence_count: 1,
  };
  assert.throws(
    () => parseChatResponse(reasoningPayload),
    (error: unknown) => (
      error instanceof ChatContractError
      && error.message.includes('reasoning.companies')
    ),
  );

  const routingPayload = currentBackendResponse();
  routingPayload.routing = { provider: 'deepseek', model: 42 };
  assert.throws(
    () => parseChatResponse(routingPayload),
    (error: unknown) => (
      error instanceof ChatContractError
      && error.message.includes('routing.model')
    ),
  );
});

test('extracts the actual routed provider and model for completion status', () => {
  const response = parseChatResponse(currentBackendResponse());

  assert.deepEqual(extractModelIdentity(response.routing), {
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
  });
  assert.equal(extractModelIdentity(null), null);
  assert.deepEqual(extractModelIdentity({ provider: 'gemini' }), {
    provider: 'gemini',
    model: null,
  });
});

test('separates the current model answer from Agent evidence analysis', () => {
  const report = splitResearchReport(`
# Research Report

## Question
How did Tesla revenue change?

## Answer (LLM Answer)
Summary

The available evidence is insufficient for a growth trend. [Evidence 1]

Key Findings

1. Automotive revenue was 82.4 billion USD.

Evidence Used

[Evidence 1]

## Agent Evidence Analysis

## Key Facts
- Tesla reported automotive revenue of 82.4 billion USD.

## Risk Signals
- Pricing pressure remains a risk.

## AI Conclusion
Collected 1 financial fact.
`);

  assert.ok(report);
  assert.equal(report.question, 'How did Tesla revenue change?');
  assert.match(report.modelAnswer, /available evidence is insufficient/);
  assert.match(report.modelAnswer, /Key Findings/);
  assert.doesNotMatch(report.modelAnswer, /Evidence Used/);
  assert.doesNotMatch(report.modelAnswer, /## Key Facts/);
  assert.equal(report.evidenceUsed, '[Evidence 1]');
  assert.match(report.agentAnalysis, /^## Key Facts/);
  assert.match(report.agentAnalysis, /## AI Conclusion/);
});

test('separates a Chinese research report into the same presentation contract', () => {
  const report = splitResearchReport(`
# 研究报告

## 问题
特斯拉 2025 年的营收增长趋势如何？

## 回答（LLM 模型回答）
摘要

总营收同比下降。[Evidence 1]

使用的证据

[Evidence 1]

## 智能体证据分析

## 关键事实
- Tesla total revenues were 41.831 billion USD.

## 来源覆盖
- Tesla_Q2_2025.pdf: 2 个文本块
`);

  assert.ok(report);
  assert.equal(report.question, '特斯拉 2025 年的营收增长趋势如何？');
  assert.match(report.modelAnswer, /总营收同比下降/);
  assert.doesNotMatch(report.modelAnswer, /智能体证据分析/);
  assert.doesNotMatch(report.modelAnswer, /使用的证据/);
  assert.equal(report.evidenceUsed, '[Evidence 1]');
  assert.match(report.agentAnalysis, /^## 关键事实/);
  assert.match(report.agentAnalysis, /## 来源覆盖/);
});

test('keeps a long model answer intact for continuous scrolling', () => {
  const modelAnswer = '这是需要通过鼠标滚轮完整阅读的模型回答。'.repeat(300);
  const report = splitResearchReport(`
# Research Report

## Question
测试长回答

## Answer
${modelAnswer}

## Agent Evidence Analysis
### Key Facts
- 测试证据
`);

  assert.ok(report);
  assert.equal(report.modelAnswer, modelAnswer);
});

test('restricted Markdown keeps raw HTML as ordinary escaped render data', () => {
  const blocks = parseRestrictedMarkdown(`
## Result

<script>alert("not executable")</script>

- **Evidence:** source.pdf
- \`model=deepseek-v4-flash\`
`);

  assert.deepEqual(blocks[0], {
    type: 'heading',
    level: 2,
    text: 'Result',
  });
  assert.deepEqual(blocks[1], {
    type: 'paragraph',
    text: '<script>alert("not executable")</script>',
  });
  assert.equal(blocks[2].type, 'unordered-list');
  assert.equal(blocks.some((block) => 'html' === block.type), false);
});

test('restricted Markdown parses pipe tables into structured table blocks', () => {
  const blocks = parseRestrictedMarkdown(`
“有多少钱”需要先明确口径。按当前可用证据，能确定的是：
| 口径 | 含义 | 当前证据下能否回答 |
|---|---|---|
| 一年赚多少钱 | 净利润 | 可以：FY2025 净利润约 **823.20 亿元** |
| 账上货币资金 | 资产负债表“货币资金” | 当前证据不足 |
`);

  assert.deepEqual(blocks[1], {
    type: 'table',
    headers: ['口径', '含义', '当前证据下能否回答'],
    rows: [
      ['一年赚多少钱', '净利润', '可以：FY2025 净利润约 **823.20 亿元**'],
      ['账上货币资金', '资产负债表“货币资金”', '当前证据不足'],
    ],
  });
  assert.equal(blocks.some((block) => (
    block.type === 'paragraph' && block.text.includes('|---|')
  )), false);
});

test('restricted Markdown groups rectangular headerless pipe rows without inventing headers', () => {
  const blocks = parseRestrictedMarkdown(`
当前检索到的证据不足以确认该信息。
| 汽车总收入 | 19,798百万美元 | 13,967百万美元 | -5,831百万美元，约-29.5% | [2]
| 能源发电与储能收入 | 3,061百万美元 | 2,730百万美元 | -331百万美元，约-10.8% | [4]
| 服务及其他收入 | 2,848百万美元 | 2,638百万美元 | -210百万美元，约-7.4% | [1]
事实：2025年第一季度总营收为19,335百万美元。 [3]
`);

  assert.equal(blocks[0].type, 'paragraph');
  assert.deepEqual(blocks[1], {
    type: 'table',
    rows: [
      ['汽车总收入', '19,798百万美元', '13,967百万美元', '-5,831百万美元，约-29.5%', '[2]'],
      ['能源发电与储能收入', '3,061百万美元', '2,730百万美元', '-331百万美元，约-10.8%', '[4]'],
      ['服务及其他收入', '2,848百万美元', '2,638百万美元', '-210百万美元，约-7.4%', '[1]'],
    ],
  });
  assert.equal(blocks[2].type, 'paragraph');
});

test('a single prose line with pipes is not promoted to a headerless table', () => {
  assert.deepEqual(parseRestrictedMarkdown('口径 | 当前证据 | 结论'), [
    { type: 'paragraph', text: '口径 | 当前证据 | 结论' },
  ]);
});

test('builds unique, sanitized citation DOM ids for each chat turn', () => {
  assert.equal(
    buildCitationDomId('chat-turn-a1', 1),
    'chat-turn-a1-evidence-1',
  );
  assert.equal(
    buildCitationDomId('chat turn/b2', 1),
    'chat-turn-b2-evidence-1',
  );
  assert.notEqual(
    buildCitationDomId('chat-turn-a1', 1),
    buildCitationDomId('chat-turn-b2', 1),
  );
  assert.equal(
    buildCitationDomId('chat-turn-a1', 2),
    'chat-turn-a1-evidence-2',
  );
});

test('parses authenticated conversation summaries and transcript messages', () => {
  const list = parseConversationList({
    items: [
      {
        thread_id: 'tenant/thread 1',
        message_count: 3,
        created_at: '2026-07-29T08:00:00Z',
        updated_at: '2026-07-29T08:05:00Z',
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
  });
  const detail = parseConversationDetail({
    session: {
      thread_id: 'tenant/thread 1',
      message_count: 3,
      created_at: '2026-07-29T08:00:00Z',
      updated_at: '2026-07-29T08:05:00Z',
    },
    messages: [
      {
        id: 1,
        role: 'system',
        content: 'internal context',
        metadata: {},
        created_at: '2026-07-29T08:00:00Z',
      },
      {
        id: 2,
        role: 'user',
        content: 'Analyze NVIDIA.',
        metadata: {},
        created_at: '2026-07-29T08:01:00Z',
      },
      {
        id: 3,
        role: 'assistant',
        content: 'NVIDIA analysis.',
        metadata: {},
        created_at: '2026-07-29T08:05:00Z',
      },
    ],
    total_messages: 3,
    limit: 500,
    offset: 0,
  });

  assert.equal(list.items[0].threadId, 'tenant/thread 1');
  assert.deepEqual(detail.messages.map((message) => message.role), [
    'user',
    'assistant',
  ]);
  assert.equal(
    buildConversationDetailPath('tenant/thread 1', 620),
    '/v1/agent/sessions/tenant%2Fthread%201'
      + '?message_limit=500&message_offset=120',
  );
});

test('restores saved generation time from transcript metadata after a refresh', () => {
  const detail = parseConversationDetail({
    session: {
      thread_id: 'duration-thread', message_count: 2,
      created_at: '2026-09-13T08:00:00Z', updated_at: '2026-09-13T08:01:00Z',
    },
    messages: [
      { id: 1, role: 'user', content: 'What is AI?', metadata: {} },
      { id: 2, role: 'assistant', content: 'An explanation.', metadata: { duration_ms: 18200 } },
      { id: 3, role: 'assistant', content: 'Legacy answer.', metadata: {} },
      { id: 4, role: 'assistant', content: 'Invalid time.', metadata: { duration_ms: -1 } },
      { id: 5, role: 'assistant', content: 'Zero time.', metadata: { duration_ms: 0 } },
    ],
    total_messages: 5, limit: 500, offset: 0,
  });
  assert.equal(detail.messages[0].durationMs, undefined);
  assert.equal(formatGenerationDuration(detail.messages[1].durationMs, 'zh-CN'), '用时 18.2 秒');
  assert.equal(detail.messages[2].durationMs, undefined);
  assert.equal(detail.messages[3].durationMs, undefined);
  assert.equal(detail.messages[4].durationMs, 0);
});

test('parses session deletion results and safely encodes delete paths', () => {
  const result = parseConversationDeleteResult({
    deleted: true,
    thread_id: '租户/thread 1',
    messages_deleted: 4,
    checkpoints_archived: 2,
    runtime_checkpoints_deleted: true,
    cache_keys_deleted: 3,
  });

  assert.deepEqual(result, {
    deleted: true,
    threadId: '租户/thread 1',
    messagesDeleted: 4,
    checkpointsArchived: 2,
    runtimeCheckpointsDeleted: true,
    cacheKeysDeleted: 3,
  });
  assert.equal(
    buildConversationDeletePath('租户/thread 1'),
    '/v1/agent/sessions/%E7%A7%9F%E6%88%B7%2Fthread%201',
  );
  assert.throws(
    () => parseConversationDeleteResult({
      deleted: false,
      thread_id: 'thread-1',
      messages_deleted: 0,
      checkpoints_archived: 0,
      runtime_checkpoints_deleted: false,
      cache_keys_deleted: 0,
    }),
    /deleted=true/,
  );
});

test('localizes fixed report headings without changing model prose', () => {
  assert.equal(localizeReportHeading('Summary', 'zh-CN'), '摘要');
  assert.equal(localizeReportHeading('Key Findings', 'zh-CN'), '关键发现');
  assert.equal(localizeReportHeading('Risks', 'zh-CN'), '风险');
  assert.equal(localizeReportHeading('Summary', 'en'), 'Summary');
  assert.equal(
    localizeReportHeading('Tesla automotive revenue', 'zh-CN'),
    'Tesla automotive revenue',
  );
});
