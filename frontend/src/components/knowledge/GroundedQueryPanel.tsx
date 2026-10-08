import { useEffect, useRef, useState } from 'react';
import { sendGroundedChatMessage } from '../../api/chat';
import { readFormalSession } from '../../api/formalUpload';
import { listReadyDocuments, readIngestionProgress, readTusSession } from '../../api/uploadSessions';
import type { ReadyDocumentOption } from '../../api/readyDocumentContract';
import { useLanguage } from '../../i18n/LanguageContext';
import type { ChatResponse } from '../../types/chat';
import { AssistantReport } from '../chat/AssistantReport';
import './GroundedQueryPanel.css';

/** Isolated pilot: readiness is rechecked for every question, never inferred from upload bytes. */
export function GroundedQueryPanel({ uploadId, formal = false }: { uploadId: string; formal?: boolean }) {
  const { language } = useLanguage();
  const zh = language === 'zh-CN';
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const listGeneration = useRef(0);
  const [options, setOptions] = useState<ReadyDocumentOption[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState('');
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [refresh, setRefresh] = useState(0);
  const primaryDocument = useRef<number | string | null>(null);
  useEffect(() => {
    generation.current += 1;
    setResponse(null); setError(''); setBusy(false);
    return () => { generation.current += 1; };
  }, [uploadId, language]);

  useEffect(() => {
    const request = ++listGeneration.current;
    const abort = new AbortController();
    setListBusy(true); setListError(''); setOptions([]); setSelected([]); setNextOffset(null);
    generation.current += 1; setResponse(null);
    void Promise.all([listReadyDocuments(0, abort.signal), formal ? readFormalSession(uploadId) : readTusSession(uploadId)]).then(([page, primary]) => {
      if (request !== listGeneration.current) return;
      primaryDocument.current = primary.documentId;
      setOptions(page.items.filter(item => String(item.documentId) !== String(primary.documentId)));
      setNextOffset(page.nextOffset);
    }).catch((failure: unknown) => {
      if (request === listGeneration.current) setListError(failure instanceof Error ? failure.message : 'Report list unavailable.');
    }).finally(() => { if (request === listGeneration.current) setListBusy(false); });
    return () => { listGeneration.current += 1; abort.abort(); };
  }, [uploadId, language, refresh, formal]);

  async function moreReports() {
    if (listBusy || nextOffset === null) return;
    const request = listGeneration.current;
    setListBusy(true); setListError('');
    try {
      const page = await listReadyDocuments(nextOffset);
      if (request !== listGeneration.current) return;
      setOptions(previous => {
        const documents = new Map(previous.map(item => [item.documentId, item]));
        for (const item of page.items) if (String(item.documentId) !== String(primaryDocument.current)) documents.set(item.documentId, item);
        return [...documents.values()];
      });
      setNextOffset(page.nextOffset);
    } catch (failure: unknown) {
      if (request === listGeneration.current) setListError(failure instanceof Error ? failure.message : 'Report list unavailable.');
    } finally { if (request === listGeneration.current) setListBusy(false); }
  }

  async function ask() {
    if (busy || listBusy || !question.trim()) return;
    const request = ++generation.current;
    setBusy(true); setResponse(null); setError('');
    try {
      const state = await readIngestionProgress(uploadId);
      if (request !== generation.current) return;
      if (state.status !== 'ready') throw new Error(zh ? '文档未处理完成或检查未通过，不能提问。' : 'Document processing is incomplete or checks did not pass.');
      const additional = options.filter(item => selected.includes(item.uploadId));
      if (additional.length !== selected.length) throw new Error('Report selection changed; refresh the list.');
      const states = await Promise.all(additional.map(item => readIngestionProgress(item.uploadId)));
      if (request !== generation.current) return;
      if (states.some((item, index) => item.status !== 'ready' || item.ingestionJobId !== additional[index].ingestionJobId)) {
        throw new Error(zh ? '所选报告状态已变化，请刷新报告列表。' : 'A selected report changed; refresh the report list.');
      }
      // Keep answer atomic in the UI: transport fragments alone are not a completed response.
      const result = await sendGroundedChatMessage(state.ingestionJobId, question, language, () => {},
        additional.map(item => item.ingestionJobId));
      if (request === generation.current) setResponse(result);
    } catch (failure: unknown) {
      if (request === generation.current) {
        setResponse(null);
        const message = failure instanceof Error ? failure.message : '';
        setError(message === 'GROUNDED_ANSWER_NOT_AVAILABLE'
          ? (zh ? '当前报告或查询方式尚不能生成经过核验的回答。请检查报告选择，或改用明确的财务指标与年度问题。'
            : 'A verified answer is not available for these reports or this query. Check the selected reports, or ask for a precise financial metric and year.')
          : (message || (zh ? '查询失败。' : 'Query failed.')));
      }
    } finally {
      if (request === generation.current) setBusy(false);
    }
  }

  return <section className="grounded-query" aria-labelledby="grounded-query-title">
    <h3 id="grounded-query-title">{formal ? (zh ? '财报提问' : 'Ask About Report') : (zh ? '财报提问（试点）' : 'Ask About Report (Pilot)')}</h3>
    <p>{zh ? '请写明指标和年份；仅依据所选财报。' : 'Specify the metric and year. Answers use selected reports only.'}</p>
    {!formal && <fieldset disabled={busy} className="grounded-query__reports">
      <legend>{zh ? '关联财报（最多再选 4 份）' : 'Additional Reports (up to 4)'}</legend>
      <p>{zh ? '当前财报已选；关联提问需后台启用。' : 'Current report included. Multi-report answers require the server pilot.'}</p>
      <button type="button" disabled={listBusy} onClick={() => setRefresh(value => value + 1)}>
        {zh ? '刷新列表' : 'Refresh Reports'}
      </button>
      {listBusy && <p role="status">{zh ? '正在检查财报状态…' : 'Checking report availability…'}</p>}
      {listError && <p role="alert">{listError}</p>}
      {!listBusy && !listError && options.length === 0 && <p>{zh ? '暂无其他可用财报。' : 'No other reports are available.'}</p>}
      {options.map(item => <label key={item.documentId} className="grounded-query__report">
        <input type="checkbox" checked={selected.includes(item.uploadId)}
          disabled={listBusy || (!selected.includes(item.uploadId) && selected.length >= 4)}
          onChange={event => {
            setSelected(previous => event.target.checked ? [...previous, item.uploadId] : previous.filter(id => id !== item.uploadId));
            generation.current += 1; setResponse(null); setError('');
          }} />
        <span>{item.filename}</span>
        <small>{zh ? '已就绪' : 'Ready'}</small>
      </label>)}
      {nextOffset !== null && <button type="button" disabled={listBusy} onClick={() => void moreReports()}>
        {zh ? '更多财报' : 'More Reports'}
      </button>}
    </fieldset>}
    <form onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor="grounded-query-question">{zh ? '输入问题' : 'Your Question'}</label>
      <textarea id="grounded-query-question" value={question} maxLength={4000} required
        disabled={busy} onChange={(event) => setQuestion(event.target.value)} />
      <button type="submit" className="upload-panel__button" disabled={busy || listBusy || !question.trim()}>
        {busy ? (zh ? '正在核对并回答…' : 'Checking sources and answering…') : (zh ? '提问' : 'Ask')}
      </button>
    </form>
    {error && <p role="alert">{error}</p>}
    {response && <AssistantReport content={response.report} response={response}
      citationNamespace={`grounded-${uploadId}`} />}
  </section>;
}
