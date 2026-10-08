import { useEffect, useState } from 'react';
import { uploadFormalPdf } from '../../api/formalUpload';
import { listReadyDocuments, readIngestionProgress } from '../../api/uploadSessions';
import type { ReadyDocumentOption } from '../../api/readyDocumentContract';
import { useLanguage } from '../../i18n/LanguageContext';
import { processingStageLabel } from '../../i18n/processingCopy';
import { GroundedQueryPanel } from './GroundedQueryPanel';

/** Formal READY is server authority; completed transport alone never enables queries. */
export function FormalUploadPanel() {
  const { language } = useLanguage();
  const zh = language === 'zh-CN';
  const [uploadId, setUploadId] = useState('');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [documents, setDocuments] = useState<ReadyDocumentOption[]>([]);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    void listReadyDocuments(0, abort.signal).then(page => setDocuments(page.items)).catch(failure => {
      if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : 'Report list unavailable');
    });
    return () => abort.abort();
  }, [refresh]);
  useEffect(() => {
    if (!uploadId) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    setReady(false);
    async function poll() {
      try {
        const progress = await readIngestionProgress(uploadId, abort.signal);
        if (abort.signal.aborted) return;
        setStatus(`${processingStageLabel(progress.stage, language)} (${progress.completedStages.length}/5)`);
        setReady(progress.status === 'ready');
        if (progress.status === 'ready') setRefresh(value => value + 1);
        else if (['failed', 'quarantined'].includes(progress.status)) setError(zh ? '处理失败或检查未通过，不能提问。' : 'Processing failed or checks did not pass. Questions are blocked.');
        else timer = setTimeout(() => void poll(), 4000);
      } catch (failure) {
        if (!abort.signal.aborted) setError(failure instanceof Error ? failure.message : 'Status unavailable');
      }
    }
    void poll();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [uploadId]);
  async function upload(file: File) {
    setBusy(true); setError(''); setReady(false); setUploadId('');
    try {
      const session = await uploadFormalPdf(file);
      setUploadId(session.uploadId);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Upload failed');
    } finally { setBusy(false); }
  }
  return <section className="upload-panel">
    <h3>{zh ? '财报上传' : 'Upload Report'}</h3>
    <p>{zh ? '完成全部检查后才能提问。' : 'Questions become available after all five checks pass.'}</p>
    <label>{zh ? '选择 PDF（最大 50 MiB）' : 'Select PDF (maximum 50 MiB)'}
      <input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={event => {
        const file = event.target.files?.[0];
        if (file) void upload(file);
        event.target.value = '';
      }} />
    </label>
    {busy && <p role="status">{zh ? '正在上传并检查文件…' : 'Uploading and verifying…'}</p>}
    {status && <p role="status">{status}</p>}
    {error && <p role="alert">{error}</p>}
    <label>{zh ? '可用财报' : 'Available Reports'}
      <select value={documents.some(item => item.uploadId === uploadId) ? uploadId : ''}
        disabled={busy} onChange={event => { setError(''); setUploadId(event.target.value); }}>
        <option value="">{zh ? '选择财报' : 'Choose Report'}</option>
        {documents.map(item => <option key={item.uploadId} value={item.uploadId}>{item.filename}</option>)}
      </select>
    </label>
    <button type="button" onClick={() => { setError(''); setRefresh(value => value + 1); }}>
      {zh ? '刷新列表' : 'Refresh Reports'}
    </button>
    {ready && uploadId && <GroundedQueryPanel uploadId={uploadId} formal />}
  </section>;
}
