import {
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
  useRef,
  useState,
} from 'react';
import { validatePdfUpload } from '../../api/knowledgeContract';
import { useLanguage } from '../../i18n/LanguageContext';
import { Icon } from '../ui/Icon';

interface InputBoxProps {
  onSubmit: (message: string) => void;
  onFileUpload: (file: File) => Promise<void>;
  disabled?: boolean;
  placeholder?: string;
}

type FileUploadState =
  | { status: 'idle' }
  | { status: 'uploading'; filename: string }
  | { status: 'success'; filename: string }
  | { status: 'error'; filename: string; detail: string };

const MAX_CONCURRENT_UPLOADS = 3;

export function InputBox({
  onSubmit,
  onFileUpload,
  disabled = false,
  placeholder,
}: InputBoxProps) {
  const { t } = useLanguage();
  const [message, setMessage] = useState('');
  const [fileUpload, setFileUpload] = useState<FileUploadState>({
    status: 'idle',
  });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadingFile = fileUpload.status === 'uploading';
  // Keep the draft editable while a response is being generated. Sending a
  // second turn is still blocked until the active request finishes, while a
  // file upload continues to lock the composer to avoid mixed states.
  const inputDisabled = uploadingFile;
  const submitDisabled = disabled || uploadingFile;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();

    if (!trimmed || submitDisabled) {
      return;
    }

    onSubmit(trimmed);
    setMessage('');
  }

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = '';

    if (files.length === 0) {
      return;
    }

    const selectedLabel = files.length === 1
      ? files[0].name
      : t.upload.selectedFiles(files.length);
    const validFiles: File[] = [];
    const failures: string[] = [];
    for (const file of files) {
      const validationIssue = validatePdfUpload(file);
      if (!validationIssue) {
        validFiles.push(file);
        continue;
      }
      failures.push(
        `${file.name}: ${validationIssue === 'too-large'
          ? t.upload.fileTooLarge
          : t.upload.invalidFileType}`,
      );
    }

    if (validFiles.length === 0) {
      setFileUpload({
        status: 'error',
        filename: selectedLabel,
        detail: failures.join('\n'),
      });
      return;
    }

    setFileUpload({ status: 'uploading', filename: selectedLabel });
    const uploadFailures: string[] = [];
    let nextIndex = 0;
    const uploadWorker = async () => {
      while (nextIndex < validFiles.length) {
        const file = validFiles[nextIndex];
        nextIndex += 1;
        try {
          await onFileUpload(file);
        } catch (error: unknown) {
          uploadFailures.push(
            `${file.name}: ${error instanceof Error ? error.message : t.upload.fallbackError}`,
          );
        }
      }
    };
    await Promise.all(
      Array.from(
        { length: Math.min(MAX_CONCURRENT_UPLOADS, validFiles.length) },
        () => uploadWorker(),
      ),
    );

    const successCount = validFiles.length - uploadFailures.length;
    const allFailures = [...failures, ...uploadFailures];
    if (allFailures.length > 0) {
      setFileUpload({
        status: 'error',
        filename: selectedLabel,
        detail: `${t.upload.batchPartial(successCount, allFailures.length)}\n${allFailures.join('\n')}`,
      });
    } else {
      setFileUpload({
        status: 'success',
        filename: files.length === 1
          ? files[0].name
          : t.upload.batchSuccess(successCount),
      });
    }
  }

  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === 'Enter'
      && !event.shiftKey
      && !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  let uploadMessage: string | null = null;
  if (fileUpload.status === 'uploading') {
    uploadMessage = t.chat.uploadingDocument(fileUpload.filename);
  } else if (fileUpload.status === 'success') {
    uploadMessage = t.chat.documentSaved(fileUpload.filename);
  } else if (fileUpload.status === 'error') {
    uploadMessage = t.chat.documentUploadFailed(
      fileUpload.filename,
      fileUpload.detail,
    );
  }

  return (
    <form className="chat-input" onSubmit={handleSubmit}>
      {uploadMessage && (
        <div
          className={`chat-input__upload-status chat-input__upload-status--${fileUpload.status}`}
          role={fileUpload.status === 'error' ? 'alert' : 'status'}
          aria-live="polite"
        >
          <span className="chat-input__upload-icon" aria-hidden="true">
            {fileUpload.status === 'uploading'
              ? '\u21BB'
              : fileUpload.status === 'success'
                ? '\u2713'
                : '!'}
          </span>
          <span>{uploadMessage}</span>
        </div>
      )}

      <div className="chat-input__composer">
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          className="chat-input__file-input"
          onChange={handleFileChange}
          tabIndex={-1}
          aria-hidden="true"
        />
        <button
          type="button"
          className="chat-input__attachment"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploadingFile || !onFileUpload}
          aria-label={t.chat.attachPdf}
          title={t.chat.attachPdf}
        >
          <Icon name="paperclip" />
          <span className="chat-input__attachment-label">PDF</span>
        </button>

        <label className="sr-only" htmlFor="chat-message-input">
          {t.chat.inputLabel}
        </label>
        <textarea
          id="chat-message-input"
          className="chat-input__message"
          rows={1}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleMessageKeyDown}
          placeholder={placeholder ?? t.chat.placeholder}
          disabled={inputDisabled}
          autoComplete="off"
        />
        <button
          type="submit"
          className="chat-input__send"
          disabled={submitDisabled || message.trim().length === 0}
        >
          <span className="chat-input__send-label">{t.chat.send}</span>
          <Icon name="arrow-up" />
        </button>
      </div>
    </form>
  );
}
