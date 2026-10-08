import { useState, useRef, type DragEvent } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import { validateDocumentUpload } from '../../api/knowledgeContract';

type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';
const MAX_CONCURRENT_UPLOADS = 3;

interface UploadPanelProps {
  onUploadSuccess: (file: File) => Promise<void>;
  onUploadComplete: () => Promise<void>;
}

export function UploadPanel({ onUploadSuccess, onUploadComplete }: UploadPanelProps) {
  const { t } = useLanguage();
  const [dragOver, setDragOver] = useState(false);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>('idle');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const doUpload = async (files: File[]) => {
    if (files.length === 0) return;

    setSelectedFile(
      files.length === 1 ? files[0].name : t.upload.selectedFiles(files.length),
    );
    setUploadError(null);

    const validFiles: File[] = [];
    const validationFailures: string[] = [];
    for (const file of files) {
      const validationIssue = validateDocumentUpload(file);
      if (!validationIssue) {
        validFiles.push(file);
        continue;
      }
      validationFailures.push(
        `${file.name}: ${validationIssue === 'too-large'
          ? t.upload.fileTooLarge
          : t.upload.invalidFileType}`,
      );
    }

    if (validFiles.length === 0) {
      setUploadStatus('error');
      setUploadError(validationFailures.join('\n'));
      return;
    }

    setUploadStatus('uploading');

    const uploadFailures: string[] = [];
    let nextIndex = 0;
    const uploadWorker = async () => {
      while (nextIndex < validFiles.length) {
        const file = validFiles[nextIndex];
        nextIndex += 1;
        try {
          await onUploadSuccess(file);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : t.upload.fallbackError;
          uploadFailures.push(`${file.name}: ${message}`);
        }
      }
    };
    await Promise.all(
      Array.from(
        { length: Math.min(MAX_CONCURRENT_UPLOADS, validFiles.length) },
        () => uploadWorker(),
      ),
    );

    await onUploadComplete();

    const successCount = validFiles.length - uploadFailures.length;
    const failures = [...validationFailures, ...uploadFailures];
    if (failures.length === 0) {
      setUploadStatus('success');
      setSelectedFile(t.upload.batchSuccess(successCount));
    } else {
      setUploadStatus('error');
      setUploadError(
        `${t.upload.batchPartial(successCount, failures.length)}\n${failures.join('\n')}`,
      );
    }
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    void doUpload(Array.from(e.dataTransfer.files));
  };

  const handleFileSelect = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    void doUpload(Array.from(e.target.files ?? []));
  };

  const handleReset = () => {
    setUploadStatus('idle');
    setSelectedFile(null);
    setUploadError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <section className="upload-panel" aria-labelledby="upload-title">
      <h2 id="upload-title" className="upload-panel__title">
        {t.upload.title}
      </h2>

      <div
        className={`upload-panel__dropzone ${dragOver ? 'upload-panel__dropzone--drag-over' : ''} upload-panel__dropzone--${uploadStatus}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={uploadStatus === 'idle' || uploadStatus === 'error' ? handleFileSelect : undefined}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            handleFileSelect();
          }
        }}
        aria-label={t.upload.ariaLabel}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.xlsx,.docx,.csv"
          multiple
          className="upload-panel__file-input"
          onChange={handleFileChange}
          aria-hidden="true"
        />

        <span className="upload-panel__dropzone-icon" aria-hidden="true">
          {uploadStatus === 'uploading' ? '\u21BB' : uploadStatus === 'success' ? '\u2713' : '\u2913'}
        </span>

        <p className="upload-panel__dropzone-text">
          {selectedFile && uploadStatus !== 'idle'
            ? selectedFile
            : {
                idle: t.upload.idle,
                uploading: t.upload.uploading,
                success: t.upload.success,
                error: t.upload.error,
              }[uploadStatus]}
        </p>

        {uploadStatus === 'idle' && (
          <span className="upload-panel__dropzone-hint">{t.upload.hint}</span>
        )}
      </div>

      {uploadError && (
        <p className="upload-panel__error" role="alert">
          <span className="upload-panel__error-icon" aria-hidden="true">&#x26A0;</span>
          {uploadError}
        </p>
      )}

      <div className="upload-panel__actions">
        {uploadStatus === 'idle' && (
          <button
            type="button"
            className="upload-panel__button"
            onClick={handleFileSelect}
          >
            {t.upload.chooseFile}
          </button>
        )}

        {uploadStatus === 'uploading' && (
          <button type="button" className="upload-panel__button upload-panel__button--disabled" disabled>
            {t.upload.uploading}
          </button>
        )}

        {uploadStatus === 'success' && (
          <button type="button" className="upload-panel__button" onClick={handleReset}>
            {t.upload.uploadAnother}
          </button>
        )}

        {uploadStatus === 'error' && (
          <button type="button" className="upload-panel__button" onClick={handleReset}>
            {t.upload.retry}
          </button>
        )}
      </div>
    </section>
  );
}
