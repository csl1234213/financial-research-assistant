import { ApiClientError, toApiUrl } from './client';
import type { RetrievalChunk, RetrievalMetrics, RetrievalResponse } from '../types/api';
import {
  parseRetrievalResponse,
  type RawApiResponse,
} from './retrievalContract';

const retrievalQueryEndpoint = '/v1/retrieval/query';

function parseJson(text: string): unknown | undefined {
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === 'string') return detail;
  const message = payload.message;
  return typeof message === 'string' ? message : fallback;
}

const isMockEnabled = import.meta.env.VITE_ENABLE_MOCK === 'true';

function mapApiResponse(raw: RawApiResponse, query: string): RetrievalResponse {
  const chunks: RetrievalChunk[] = (raw.chunks ?? []).map((c) => ({
    filename: typeof c.metadata?.filename === 'string' ? c.metadata.filename : 'Unknown',
    page: typeof c.metadata?.page === 'string' ? Number(c.metadata.page) || 0 : (typeof c.metadata?.page === 'number' ? c.metadata.page : 0),
    content: c.content ?? '',
    score: c.score ?? 0,
  }));

  const rawMetrics = raw.metrics ?? {};

  const metrics: RetrievalMetrics = {
    latencyMs: rawMetrics.latency_ms ?? rawMetrics.latency ?? 0,
    chunkCount: chunks.length,
    retrieverType: rawMetrics.retriever_type ?? 'unknown',
  };

  return {
    query: raw.query ?? query,
    chunks,
    metrics,
  };
}

function generateMockResults(query: string): RetrievalResponse {
  const queryLower = query.toLowerCase();
  const isTesla = queryLower.includes('tesla');
  const isNvidia = queryLower.includes('nvidia');
  const isRevenue = queryLower.includes('revenue');

  const mockChunks: RetrievalChunk[] = [
    {
      filename: isTesla ? 'Tesla_Q2_2025.pdf' : 'Tesla_Q3_2025.pdf',
      page: 1,
      content: isTesla && isRevenue
        ? 'Tesla, Inc. reported record quarterly revenue of $24.93 billion in Q2 2025, representing a 47% increase year-over-year. The company delivered 466,140 vehicles globally during the quarter.'
        : 'Tesla achieved automotive gross margin of 18.2% in Q3 2025, up from 16.3% in the previous quarter. Total revenue reached $25.18 billion.',
      score: 0.95,
    },
    {
      filename: isNvidia ? 'NVIDIA_Report.pdf' : 'Tesla_Q2_2025.pdf',
      page: isNvidia ? 3 : 7,
      content: isNvidia
        ? 'NVIDIA reported data center revenue of $30.8 billion in Q3 FY2025, up 112% year-over-year driven by Hopper architecture demand.'
        : 'Energy generation and storage revenue grew 74% YoY to $4.2 billion. Megapack deployments reached a record 9.4 GWh during the quarter.',
      score: 0.89,
    },
    {
      filename: isTesla ? 'Tesla_Q3_2025.pdf' : 'NVIDIA_Report.pdf',
      page: isTesla ? 5 : 8,
      content: isTesla
        ? 'Tesla\'s free cash flow was $2.3 billion, with $28.5 billion in cash and equivalents. Operating margin improved to 10.8% in Q3 2025.'
        : 'NVIDIA\'s automotive segment revenue grew 37% YoY to $449 million, driven by autonomous vehicle platform adoption.',
      score: 0.82,
    },
    {
      filename: isNvidia ? 'NVIDIA_Report.pdf' : 'Apple_Annual_2025.pdf',
      page: 12,
      content: isNvidia
        ? 'Gross margin reached 75.1% in Q3 FY2025, reflecting strong product mix and operational efficiencies across the data center segment.'
        : 'Apple\'s services revenue reached an all-time high of $24.2 billion in Q4 2025, with over 1 billion paid subscriptions across the platform.',
      score: 0.76,
    },
    {
      filename: isTesla ? 'Tesla_Q2_2025.pdf' : 'Microsoft_10K.pdf',
      page: isTesla ? 15 : 22,
      content: isTesla
        ? 'R&D expenses totaled $1.1 billion in Q2 2025, reflecting continued investment in Full Self-Driving (FSD) technology and Optimus robot program.'
        : 'Microsoft Cloud revenue exceeded $38 billion in Q1 FY2026, with Azure revenue growth of 33% driving overall commercial cloud momentum.',
      score: 0.71,
    },
  ];

  return {
    query,
    chunks: mockChunks,
    metrics: {
      latencyMs: 45 + Math.floor(Math.random() * 30),
      chunkCount: mockChunks.length,
      retrieverType: 'hybrid_search',
    },
  };
}

export async function queryRetrieval(
  query: string,
  topK: number = 5,
): Promise<RetrievalResponse> {
  try {
    const response = await fetch(toApiUrl(retrievalQueryEndpoint), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, top_k: topK }),
    });

    const payload = parseJson(await response.text());

    if (!response.ok) {
      throw new ApiClientError(
        getErrorMessage(payload, `Retrieval query failed with status ${response.status}.`),
        response.status,
        payload,
      );
    }

    if (payload === undefined) {
      throw new ApiClientError('The API returned an invalid JSON response.', response.status);
    }

    return mapApiResponse(parseRetrievalResponse(payload), query);
  } catch (err) {
    if (isMockEnabled) {
      return generateMockResults(query);
    }
    throw err;
  }
}
