export interface RawApiChunk {
  content: string;
  metadata?: Record<string, unknown>;
  score: number;
}

export interface RawApiMetrics {
  latency?: number;
  latency_ms?: number;
  retriever_type?: string;
}

export interface RawApiResponse {
  query?: string;
  chunks?: RawApiChunk[];
  metrics?: RawApiMetrics;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireFiniteNumber(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number.`);
  }
  return value;
}

function parseRawChunk(value: unknown, index: number): RawApiChunk {
  if (!isRecord(value)) {
    throw new Error(`chunks[${index}] must be an object.`);
  }
  if (typeof value.content !== 'string') {
    throw new Error(`chunks[${index}].content must be a string.`);
  }
  const metadata = value.metadata;
  if (metadata !== undefined && !isRecord(metadata)) {
    throw new Error(`chunks[${index}].metadata must be an object when present.`);
  }
  return {
    content: value.content,
    score: requireFiniteNumber(value.score, `chunks[${index}].score`),
    ...(metadata === undefined ? {} : { metadata }),
  };
}

export function parseRetrievalResponse(value: unknown): RawApiResponse {
  if (!isRecord(value)) {
    throw new Error('retrieval response must be an object.');
  }
  const query = value.query;
  if (query !== undefined && typeof query !== 'string') {
    throw new Error('retrieval response query must be a string when present.');
  }
  const chunks = value.chunks;
  if (chunks !== undefined && !Array.isArray(chunks)) {
    throw new Error('retrieval response chunks must be an array when present.');
  }
  const metrics = value.metrics;
  if (metrics !== undefined && !isRecord(metrics)) {
    throw new Error('retrieval response metrics must be an object when present.');
  }
  const parsedMetrics: RawApiMetrics | undefined = metrics === undefined
    ? undefined
    : {
      ...(metrics.latency === undefined
        ? {}
        : { latency: requireFiniteNumber(metrics.latency, 'metrics.latency') }),
      ...(metrics.latency_ms === undefined
        ? {}
        : { latency_ms: requireFiniteNumber(metrics.latency_ms, 'metrics.latency_ms') }),
      ...(metrics.retriever_type === undefined
        ? {}
        : typeof metrics.retriever_type === 'string'
          ? { retriever_type: metrics.retriever_type }
          : (() => {
            throw new Error('metrics.retriever_type must be a string when present.');
          })()),
    };
  return {
    ...(query === undefined ? {} : { query }),
    ...(chunks === undefined ? {} : { chunks: chunks.map(parseRawChunk) }),
    ...(parsedMetrics === undefined ? {} : { metrics: parsedMetrics }),
  };
}
