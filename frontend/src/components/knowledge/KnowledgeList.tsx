import { DocumentCard } from './DocumentCard';
import { useLanguage } from '../../i18n/LanguageContext';
import type { KnowledgeDocument } from '../../types/knowledge';

interface KnowledgeListProps {
  documents: KnowledgeDocument[];
  onDocumentDelete: (document: KnowledgeDocument) => void;
  deletingDocumentId?: string | null;
}

export function KnowledgeList({
  documents,
  onDocumentDelete,
  deletingDocumentId,
}: KnowledgeListProps) {
  const { t } = useLanguage();

  if (documents.length === 0) {
    return (
      <div className="knowledge-empty">
        <span className="knowledge-empty__icon" aria-hidden="true">📂</span>
        <p className="knowledge-empty__title">{t.knowledge.emptyTitle}</p>
        <p className="knowledge-empty__hint">
          {t.knowledge.emptyHint}
        </p>
      </div>
    );
  }

  return (
    <div className="knowledge-list">
      {documents.map((doc) => (
        <DocumentCard
          key={doc.id}
          filename={doc.filename}
          company={doc.company}
          pages={doc.pages}
          status={doc.status}
          size={doc.size}
          uploadedAt={doc.uploadedAt}
          period={doc.period}
          chunkCount={doc.chunkCount}
          contentSha256={doc.contentSha256}
          sourceUrl={doc.sourceUrl}
          sourceType={doc.sourceType}
          onDelete={doc.canDelete ? () => onDocumentDelete(doc) : undefined}
          deleting={deletingDocumentId === doc.id}
        />
      ))}
    </div>
  );
}
