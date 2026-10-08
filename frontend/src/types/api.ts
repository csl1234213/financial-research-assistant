// ============================================================
// Unified API Types — aligned with backend schemas
// ============================================================

// ---- Chat / Agent ----

export interface Citation {
  rank: number;
  source: string;
  chunk_id: string;
  similarity: number | null;
  preview: string;
  page?: number;
  page_label?: string;
  source_locator?: string;
  document_id?: string;
  content_sha256?: string;
  content_type?: string;
  source_format?: string;
}

export interface Reasoning {
  intent: string;
  companies: string[];
  research_mode: string;
  evidence_count: number;
}

export interface Execution {
  strategy: string;
  [key: string]: unknown;
}

export interface Workflow {
  type: string;
  status: string;
  [key: string]: unknown;
}

export interface Plan {
  steps?: string[];
  queries?: string[];
  [key: string]: unknown;
}

export interface Routing {
  provider: string;
  agent?: string;
  pipeline?: string;
  [key: string]: unknown;
}

export interface Planning {
  intent?: string;
  companies?: string[];
  research_mode?: string;
  [key: string]: unknown;
}

/**
 * Full chat response contract matching backend schemas/response.py ChatResponse.
 */
export interface ChatResponse {
  financialPresentation?: import('../api/financialPresentationContract').FinancialPresentation | null;
  report: string;
  citations: Citation[];
  reasoning: Reasoning;
  plan: Plan;
  execution_time: number;
  routing: Routing | null;
  planning: Planning | null;
  execution: Execution | null;
  workflow: Workflow | null;
}

// ---- Knowledge ----

export type DocumentStatus = 'indexed' | 'processing' | 'failed' | 'quarantined';

export interface KnowledgeDocument {
  id: string;
  filename: string;
  company: string;
  period?: string;
  pages: number;
  status: DocumentStatus;
  uploadedAt: string;
  size?: string;
  byteSize?: number;
  chunkCount?: number;
  contentSha256?: string;
  sourceUrl?: string;
  sourceType?: 'sec_edgar' | 'cninfo';
  canDelete?: boolean;
}

export interface DocumentDetail extends KnowledgeDocument {
  chunkCount: number;
  embeddingStatus: 'completed' | 'pending' | 'failed';
  vectorStatus: 'stored' | 'pending' | 'failed';
  fileSize?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface DocumentChunk {
  index: number;
  content: string;
  metadata: Record<string, string>;
  score?: number;
}

// ---- Retrieval ----

export interface RetrievalChunk {
  filename: string;
  page: number;
  content: string;
  score: number;
}

export interface RetrievalMetrics {
  latencyMs: number;
  chunkCount: number;
  retrieverType: string;
}

export interface RetrievalResponse {
  query: string;
  chunks: RetrievalChunk[];
  metrics: RetrievalMetrics;
}

// ---- Health ----

export interface HealthResponse {
  status: 'ok' | 'healthy' | 'degraded' | 'unhealthy';
  version?: string;
  uptime?: number;
  components?: Record<string, 'up' | 'down' | 'degraded'>;
}

// ---- Error ----

export interface ApiErrorDetail {
  detail?: string;
  message?: string;
  errors?: unknown[];
  code?: string;
}

// ---- Chat Message (UI) ----

export interface ChatMessage {
  financialPresentation?: import('../api/financialPresentationContract').FinancialPresentation | null;
  savedCitations?: Citation[];
  id: string;
  role: 'user' | 'assistant';
  content: string;
  response?: ChatResponse;
  citationNamespace?: string;
  durationMs?: number;
}
