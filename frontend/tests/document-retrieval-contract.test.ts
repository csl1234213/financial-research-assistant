import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DocumentContractError,
  parseDocumentChunks,
  parseDocumentDetail,
} from '../src/api/documentContract.ts';
import { parseRetrievalResponse } from '../src/api/retrievalContract.ts';

test('parses document detail and chunk contracts from the live snake-case API', () => {
  const document = parseDocumentDetail({
    id: '17',
    filename: 'NVIDIA.pdf',
    company: 'NVIDIA',
    period: 'Q1 FY2027',
    pages: 43,
    status: 'indexed',
    uploaded_at: '2026-09-23T08:00:00Z',
    chunk_count: 43,
    embedding_status: 'completed',
    vector_status: 'stored',
  });
  assert.equal(document.chunkCount, 43);
  assert.equal(document.uploadedAt, '2026-09-23T08:00:00Z');

  const chunks = parseDocumentChunks([
    {
      index: 0,
      content: 'Revenue was $81.6 billion.',
      metadata: { page: '1', source: 'NVIDIA.pdf' },
      score: 0.98,
    },
  ]);
  assert.equal(chunks[0].metadata.source, 'NVIDIA.pdf');
  assert.equal(chunks[0].score, 0.98);
});

test('rejects malformed document and retrieval payloads instead of returning empty data', () => {
  assert.throws(
    () => parseDocumentDetail({
      id: '17', filename: 'NVIDIA.pdf', company: 'NVIDIA', pages: 43,
      status: 'unknown', uploaded_at: '2026-09-23T08:00:00Z', chunk_count: 43,
      embedding_status: 'completed', vector_status: 'stored',
    }),
    DocumentContractError,
  );
  assert.throws(
    () => parseDocumentChunks([{
      index: 0, content: 'bad metadata', metadata: { page: 1 },
    }]),
    DocumentContractError,
  );
  assert.deepEqual(
    parseRetrievalResponse({
      query: 'revenue',
      chunks: [{ content: 'evidence', score: 0.9, metadata: { page: '1' } }],
      metrics: { latency_ms: 12, retriever_type: 'hybrid' },
    }),
    {
      query: 'revenue',
      chunks: [{ content: 'evidence', score: 0.9, metadata: { page: '1' } }],
      metrics: { latency_ms: 12, retriever_type: 'hybrid' },
    },
  );
  assert.throws(
    () => parseRetrievalResponse({ chunks: [{ content: 'evidence', score: '0.9' }] }),
    /score must be a finite number/,
  );
});
