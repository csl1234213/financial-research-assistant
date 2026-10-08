import { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { Header } from '../components/layout/Header';
import { KnowledgeHeader } from '../components/knowledge/KnowledgeHeader';
import { KnowledgeList } from '../components/knowledge/KnowledgeList';
import { UploadPanel } from '../components/knowledge/UploadPanel';
import { ResumableUploadPanel } from '../components/knowledge/ResumableUploadPanel';
import { FormalUploadPanel } from '../components/knowledge/FormalUploadPanel';
import {
  deleteDocument,
  getDocuments,
  getDocumentQuota,
  refreshKnowledge,
  uploadDocument,
} from '../api/knowledge';
import { ApiClientError } from '../api/client';
import { useLanguage } from '../i18n/LanguageContext';
import { Icon } from '../components/ui/Icon';
import type { KnowledgeDocument } from '../types/knowledge';
import type { DocumentQuota } from '../api/knowledge';
import type { AuthUser } from '../types/auth';

export function Knowledge({ user }: { user: AuthUser }) {
  const { t, language } = useLanguage();
  const [quota, setQuota] = useState<DocumentQuota | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const listRequest = useRef(0);

  const loadDocuments = useCallback(async () => {
    const requestId = ++listRequest.current;
    setLoading(true);
    setError(null);
    try {
      const docs = await getDocuments();
      const nextQuota = await getDocumentQuota();
      if (requestId !== listRequest.current) return;
      setDocuments(docs);
      setQuota(nextQuota);
    } catch (err: unknown) {
      if (requestId !== listRequest.current) return;
      const message = err instanceof Error ? err.message : t.knowledge.connectionError;
      setError(message);
    } finally {
      if (requestId === listRequest.current) setLoading(false);
    }
  }, [t.knowledge.connectionError]);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleRefresh = useCallback(async () => {
    const requestId = ++listRequest.current;
    setLoading(true);
    setError(null);
    try {
      const docs = await refreshKnowledge();
      const nextQuota = await getDocumentQuota();
      if (requestId !== listRequest.current) return;
      setDocuments(docs);
      setQuota(nextQuota);
    } catch (err: unknown) {
      if (requestId !== listRequest.current) return;
      const message = err instanceof Error ? err.message : t.knowledge.connectionError;
      setError(message);
    } finally {
      if (requestId === listRequest.current) setLoading(false);
    }
  }, [t.knowledge.connectionError]);

  const handleUpload = useCallback(async (file: File) => {
    try {
      await uploadDocument(file);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        if (err.status === 400) {
          throw new Error(t.upload.invalidDocument);
        }
        if (err.status === 409) {
          throw new Error(t.upload.duplicateDocument);
        }
        if (err.status === 413) {
          throw new Error(t.upload.fileTooLarge);
        }
        if (err.status === 429) {
          const detail = err.detail?.detail?.toLowerCase() ?? '';
          throw new Error(
            detail.includes('upload limit')
              ? t.upload.uploadLimitExceeded
              : t.upload.rateLimited,
          );
        }
      }
      throw err;
    }
  }, [
    t.upload.duplicateDocument,
    t.upload.fileTooLarge,
    t.upload.invalidDocument,
    t.upload.rateLimited,
    t.upload.uploadLimitExceeded,
  ]);

  const handleUploadComplete = useCallback(async () => {
    setNotice(null);
    await loadDocuments();
  }, [loadDocuments]);

  const handleDelete = useCallback(async (document: KnowledgeDocument) => {
    if (!window.confirm(t.knowledge.deleteConfirm(document.filename))) {
      return;
    }

    setDeletingDocumentId(document.id);
    setError(null);
    setNotice(null);
    try {
      await deleteDocument(document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setQuota(await getDocumentQuota());
      setNotice(t.knowledge.deleteSuccess(document.filename));
    } catch (err: unknown) {
      const message = err instanceof Error
        ? err.message
        : t.knowledge.deleteFailed;
      setError(message);
    } finally {
      setDeletingDocumentId(null);
    }
  }, [
    t.knowledge.deleteConfirm,
    t.knowledge.deleteFailed,
    t.knowledge.deleteSuccess,
  ]);

  const filteredDocs = useMemo(() => {
    if (!searchQuery.trim()) return documents;
    const q = searchQuery.toLowerCase();
    return documents.filter(
      (doc) =>
        doc.filename.toLowerCase().includes(q) ||
        (doc.company ?? '').toLowerCase().includes(q),
    );
  }, [documents, searchQuery]);

  const indexedCount = documents.filter((d) => d.status === 'indexed').length;
  const processingCount = documents.filter((d) => d.status === 'processing').length;
  const failedCount = documents.filter((d) => d.status === 'failed').length;

  return (
    <div className="app-layout">
      <Header
        title={t.header.title}
        subtitle={t.header.knowledgeSubtitle}
        connected
      />

      <div className="knowledge-layout">
        <div className="knowledge-layout__header">
          <KnowledgeHeader
            documentCount={documents.length}
            indexedCount={indexedCount}
            processingCount={processingCount}
            failedCount={failedCount}
            onRefresh={handleRefresh}
            refreshing={loading}
          />

          <div className="knowledge-search">
            <span className="knowledge-search__icon" aria-hidden="true">
              <Icon name="search" />
            </span>
            <input
              type="text"
              className="knowledge-search__input"
              placeholder={t.knowledge.searchPlaceholder}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label={t.knowledge.searchLabel}
            />
          </div>
        </div>

        <div className="knowledge-layout__body">
          <main className="knowledge-main">
            <section className="knowledge-section" aria-labelledby="documents-title">
              <h2 id="documents-title" className="knowledge-section__title">
                {t.knowledge.documents}
              </h2>
              {error && (
                <div className="knowledge-error" role="alert">
                  <span className="knowledge-error__icon" aria-hidden="true">&#x26A0;</span>
                  {error}
                </div>
              )}
              {notice && (
                <div className="knowledge-success" role="status">
                  <span aria-hidden="true">&#x2713;</span>
                  {notice}
                </div>
              )}
              <KnowledgeList
                documents={filteredDocs}
                onDocumentDelete={handleDelete}
                deletingDocumentId={deletingDocumentId}
              />
            </section>
          </main>

          <aside className="knowledge-sidebar">
            {quota && (
              <p role="status">
                {quota.bypassed
                  ? t.knowledge.quotaBypassed
                  : language === 'zh-CN'
                  ? `已用 ${quota.used} / ${quota.limit} 份（删除文档后释放额度）`
                  : `${quota.used} / ${quota.limit} documents used (deleting frees capacity)`}
              </p>
            )}
            <FormalUploadPanel key={`formal:${user.id}`} />
            {import.meta.env.VITE_RESUMABLE_UPLOAD_PILOT === 'true' && user.tenant ? <ResumableUploadPanel
              key={`${user.tenant.id}:${user.id}`} tenantId={user.tenant.id} userId={user.id}
              onDocumentStateChange={handleUploadComplete} /> : <UploadPanel
              onUploadSuccess={handleUpload}
              onUploadComplete={handleUploadComplete}
            />}
          </aside>
        </div>
      </div>
    </div>
  );
}
