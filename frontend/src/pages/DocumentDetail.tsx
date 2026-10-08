import { useState, useEffect, useCallback } from 'react';
import { Header } from '../components/layout/Header';
import { DocumentHeader } from '../components/document/DocumentHeader';
import { DocumentStats } from '../components/document/DocumentStats';
import { ChunkList } from '../components/document/ChunkList';
import { getDocument, getDocumentChunks } from '../api/document';
import { useLanguage } from '../i18n/LanguageContext';
import type { DocumentDetail as DocumentDetailType, DocumentChunk } from '../types/knowledge';

interface DocumentDetailProps {
  documentId: string;
  onBack: () => void;
}

export function DocumentDetail({ documentId, onBack }: DocumentDetailProps) {
  const { t } = useLanguage();
  const [document, setDocument] = useState<DocumentDetailType | null>(null);
  const [chunks, setChunks] = useState<DocumentChunk[]>([]);
  const [loading, setLoading] = useState(true);
  const [chunksLoading, setChunksLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDocument = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const doc = await getDocument(documentId);
      setDocument(doc);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : t.document.loadFailed;
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [documentId, t.document.loadFailed]);

  const loadChunks = useCallback(async () => {
    setChunksLoading(true);
    try {
      const chunkData = await getDocumentChunks(documentId);
      setChunks(chunkData);
    } catch {
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    loadDocument();
    loadChunks();
  }, [loadDocument, loadChunks]);

  return (
    <div className="app-layout">
      <Header
        title={t.header.title}
        subtitle={t.header.documentSubtitle}
        connected
      />

      <div className="doc-detail-layout">
        {loading && (
          <div className="doc-detail-layout__loading">
            <div className="doc-detail-skeleton">
              <div className="doc-detail-skeleton__header" />
              <div className="doc-detail-skeleton__meta" />
              <div className="doc-detail-skeleton__stats" />
            </div>
          </div>
        )}

        {error && !loading && (
          <div className="doc-detail-layout__error" role="alert">
            <span className="doc-detail-layout__error-icon" aria-hidden="true">
              &#x26A0;
            </span>
            <div className="doc-detail-layout__error-body">
              <p className="doc-detail-layout__error-title">{t.document.loadFailedTitle}</p>
              <p className="doc-detail-layout__error-message">{error}</p>
            </div>
            <button
              type="button"
              className="doc-detail-layout__error-back"
              onClick={onBack}
            >
              {t.document.backToDocuments}
            </button>
          </div>
        )}

        {document && !loading && (
          <>
            <DocumentHeader document={document} onBack={onBack} />
            <DocumentStats document={document} />

            <section className="doc-chunk-section" aria-labelledby="chunk-explorer-title">
              <h2 id="chunk-explorer-title" className="doc-chunk-section__title">
                {t.document.chunkExplorer}
              </h2>
              <ChunkList chunks={chunks} loading={chunksLoading} />
            </section>
          </>
        )}
      </div>
    </div>
  );
}
