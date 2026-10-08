import { useEffect, useRef, useState } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import { processingStageLabel } from '../../i18n/processingCopy';
import { createResumableUpload } from '../../api/resumableUpload';
import { verifyRecoverySelection } from '../../api/resumableUploadContract';
import { createTusSession, readTusSession, verifyTusSession, finalizeTusSession, readIngestionProgress } from '../../api/uploadSessions';
import { getAccessToken } from '../../api/session';
import { toApiUrl } from '../../api/client';
import { uploadRecoveryKey, readUploadRecovery, rememberUploadRecovery } from '../../api/uploadRecovery';
import { createIngestionInvalidator } from '../../api/ingestionInvalidation';
import { GroundedQueryPanel } from './GroundedQueryPanel';

/** Opt-in standard transport pilot, not an ingestion READY indicator. */
export function ResumableUploadPanel({ tenantId, userId, onDocumentStateChange }: {
  tenantId: number; userId: number; onDocumentStateChange?: () => void | Promise<void>;
}) {
  const { language } = useLanguage();
  const zh = language === 'zh-CN';
  const [uploadId, setUploadId] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState(false);
  const [progress, setProgress] = useState(0);
  const [ingestionId, setIngestionId] = useState<string | null>(null);
  const [readyJob, setReadyJob] = useState<string | null>(null);
  const controller = useRef<ReturnType<typeof createResumableUpload> | null>(null);
  const recoveryRequest = useRef(0);
  const documentStateChange = useRef(onDocumentStateChange);
  const invalidator = useRef(createIngestionInvalidator(() => documentStateChange.current?.()));
  useEffect(() => { documentStateChange.current = onDocumentStateChange; }, [onDocumentStateChange]);
  function notifyDocumentState(id: string, state: string) {
    // Invalidate the list; never manufacture a local READY document. The parent
    // reads authoritative documents/quota and owns list-refresh error handling.
    invalidator.current(id, state);
  }
  const recoveryKey = uploadRecoveryKey(tenantId, userId);
  useEffect(() => {
    let cancelled = false;
    const requestId = ++recoveryRequest.current;
    const remembered = readUploadRecovery(window.localStorage, recoveryKey);
    if (remembered) {
      // An old/tampered hint cannot authorize transport or query readiness.
      void readTusSession(remembered).then((session) => {
        if (cancelled || recoveryRequest.current !== requestId) return;
        // Display persisted progress only; actual resume still uses tus HEAD.
        // A completed upload must not visually reset to zero after refresh.
        setProgress(session.bytesReceived === null ? 0 : session.bytesReceived / session.expectedSize);
        recover(session.uploadId, session.status);
      }).catch(() => {
        if (!cancelled && recoveryRequest.current === requestId) {
          setError(true);
          setMessage(zh ? '无法确认之前的上传，请检查登录状态或开始新上传。' : 'Previous upload could not be verified; check login or start a new upload.');
        }
      });
    }
    function recover(id: string, status: string) {
      setUploadId(id);
      if (status === 'FINALIZED') setIngestionId(id);
      else setMessage(zh ? '已恢复记录，请选原 PDF 继续上传。' : 'Upload restored. Select the original PDF to continue.');
    }
    return () => { cancelled = true; };
  }, [recoveryKey, zh]);
  useEffect(() => () => controller.current?.destroy(), []);
  useEffect(() => {
    if (!ingestionId) return;
    setReadyJob(null);
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let requestTimeout: ReturnType<typeof setTimeout>;
    let request: AbortController | null = null;
    let attempts = 0;
    const poll = async () => {
      try {
        request = new AbortController();
        requestTimeout = setTimeout(() => request?.abort(), 10000);
        const state = await readIngestionProgress(ingestionId, request.signal);
        clearTimeout(requestTimeout);
        if (cancelled) return;
        notifyDocumentState(ingestionId, `${state.status}:${state.stage}`);
        if (state.status === 'ready') {
          setReadyJob(ingestionId);
          setMessage(zh ? '文档处理完成，可以提问。' : 'Processing complete. You can now ask questions.'); return;
        }
        if (state.status === 'failed' || state.status === 'quarantined') {
          setError(true); setMessage(zh ? '处理失败或检查未通过，不能提问。' : 'Processing failed or checks did not pass. Questions are blocked.'); return;
        }
        setMessage(`${zh ? '处理中' : 'Processing'}: ${processingStageLabel(state.stage, language)} (${state.completedStages.length}/5)`);
      } catch (failure: unknown) {
        clearTimeout(requestTimeout);
        if (cancelled) return;
        setError(true); setMessage(failure instanceof Error ? failure.message : 'Progress unavailable'); return;
      }
      attempts += 1;
      if (attempts < 60) timer = setTimeout(poll, 2000);
      else setMessage(zh ? '仍在处理，请点“查看进度”。' : 'Still processing. Select Check Progress to update.');
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); clearTimeout(requestTimeout); request?.abort(); };
  }, [ingestionId, zh]);

  async function run(file: File) {
    if (busy) return;
    recoveryRequest.current += 1;
    setBusy(true); setError(false); setProgress(0); setIngestionId(null); setReadyJob(null);
    try {
      let session;
      if (uploadId) {
        session = await readTusSession(uploadId.trim());
      } else {
        if (file.size <= 0 || file.size > 50 * 1024 * 1024 || !file.name.toLowerCase().endsWith('.pdf')) {
          throw new Error(zh ? '请选择不超过 50 MB 的 PDF。' : 'Select a PDF no larger than 50 MB.');
        }
        const bytes = await file.arrayBuffer();
        if (new TextDecoder().decode(bytes.slice(0, 5)) !== '%PDF-') throw new Error('PDF content required');
        const sha = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
          (byte) => byte.toString(16).padStart(2, '0')).join('');
        session = await createTusSession(file.name, file.size, sha);
        setUploadId(session.uploadId);
      }
      const state = await verifyRecoverySelection(file, session);
      rememberUploadRecovery(window.localStorage, recoveryKey, session.uploadId);
      if (state !== 'complete') {
        setMessage(zh ? '正在传输文件…' : 'Transferring file…');
        controller.current?.destroy();
        const transport = createResumableUpload({ uploadId: session.uploadId,
          gatewayUrl: toApiUrl(`/v1/upload-transport/${session.uploadId}`), origin: window.location.origin,
          getToken: getAccessToken, expectedSize: session.expectedSize, expectedSha256: session.expectedSha256,
          existingResource: state === 'resume', onProgress: (bytes, total) => setProgress(total ? bytes / total : 0) });
        controller.current = transport;
        await transport.selectFile(file);
        const result = await transport.upload();
        if (!result || result.failed?.length || !result.successful?.length) throw new Error('Upload did not complete');
      }
      if (session.status !== 'FINALIZED') {
        setMessage(zh ? '正在检查文件并安排处理…' : 'Checking the file and queuing processing…');
        await verifyTusSession(session.uploadId);
        await finalizeTusSession(session.uploadId);
      }
      setMessage(zh ? '已安排处理，完成检查后才能提问。' : 'Processing queued. The document is not ready for questions yet.');
      notifyDocumentState(session.uploadId, 'registered');
      setIngestionId(session.uploadId);
    } catch (failure: unknown) {
      setError(true);
      setMessage(failure instanceof Error ? failure.message : (zh ? '上传失败，请重试。' : 'Upload failed; retry.'));
    } finally { setBusy(false); }
  }

  return <section className="upload-panel" aria-labelledby="resumable-title">
    <h2 id="resumable-title" className="upload-panel__title">{zh ? '断点上传（试点）' : 'Resume Upload (Pilot)'}</h2>
    <p>{zh ? '刷新后恢复上传记录；续传请选原文件。' : 'After refresh, reselect the original file to resume your upload.'}</p>
    <label htmlFor="resume-upload-id">{zh ? '上传编号（新上传留空）' : 'Upload Reference (blank for new upload)'}</label>
    <input id="resume-upload-id" value={uploadId} onChange={(event) => {
      recoveryRequest.current += 1; setUploadId(event.target.value); setReadyJob(null); setIngestionId(null);
    }} disabled={busy} autoComplete="off" />
    <label htmlFor="resume-upload-file">{zh ? '选择文件' : 'Choose PDF'}</label>
    <input id="resume-upload-file" type="file" accept=".pdf" disabled={busy} onChange={(event) => {
      const file = event.target.files?.[0]; event.target.value = ''; if (file) void run(file);
    }} />
    <progress value={progress} max={1} aria-label={zh ? '上传进度' : 'Upload Progress'} />
    <button type="button" disabled={busy} onClick={() => {
      recoveryRequest.current += 1;
      try { window.localStorage.removeItem(recoveryKey); } catch { /* Storage can be unavailable. */ }
      controller.current?.destroy(); controller.current = null;
      setUploadId(''); setIngestionId(null); setReadyJob(null); setMessage(''); setError(false); setProgress(0);
    }}>{zh ? '新建上传' : 'New Upload'}</button>
    <button type="button" className="upload-panel__button" disabled={busy || !uploadId}
      onClick={() => { setError(false); setReadyJob(null); setIngestionId(null); void readTusSession(uploadId.trim()).then((value) => {
        if (value.status !== 'FINALIZED') throw new Error(zh ? '尚未安排文档处理。' : 'Document processing has not been queued.');
        setIngestionId(value.uploadId);
      }).catch((failure: unknown) => { setError(true); setMessage(failure instanceof Error ? failure.message : 'Progress unavailable'); }); }}>
      {zh ? '查看进度' : 'Check Progress'}
    </button>
    {message && <p role={error ? 'alert' : 'status'} className={error ? 'upload-panel__error' : ''}>{message}</p>}
    {readyJob && import.meta.env.VITE_GROUNDED_ANSWER_PILOT === 'true'
      && <GroundedQueryPanel key={readyJob} uploadId={readyJob} />}
  </section>;
}
