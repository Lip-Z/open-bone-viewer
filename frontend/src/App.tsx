import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowUpRight, Bone, Box, ChevronRight, CircleHelp, FileImage, FlaskConical, FolderOpen, HardDrive, Layers, LoaderCircle, Plus, ScanLine, ShieldCheck, Trash2, Upload, X } from 'lucide-react';
import { CtViewer } from './CtViewer';
import { XrayViewer } from './XrayViewer';
import { useHelp } from './HelpContext';
import { api, assetUrl, loadGzip, localText, studyLabel, waitForJob } from './types';
import type { CtMetadata, Job, Study, XrayMetadata } from './types';

type ImportResult = { studies: Study[]; warnings: string[] };

export function App() {
  const { openHelp } = useHelp();
  const [studies, setStudies] = useState<Study[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [meta, setMeta] = useState<CtMetadata | null>(null);
  const [volume, setVolume] = useState<Float32Array | null>(null);
  const [image, setImage] = useState<XrayMetadata | null>(null);
  const [loadedStudyId, setLoadedStudyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notices, setNotices] = useState<string[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [importing, setImporting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [reload, setReload] = useState(0);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const selected = studies.find(study => study.id === selectedId);

  useEffect(() => {
    const abort = new AbortController();
    api<{ studies: Study[] }>('/studies', { signal: abort.signal }).then(result => {
      setStudies(result.studies);
      const requested = new URLSearchParams(window.location.search).get('study');
      setSelectedId(result.studies.find(study => study.id === requested)?.id ?? result.studies.find(study => study.supported && study.kind === 'ct')?.id ?? result.studies.find(study => study.supported)?.id ?? result.studies[0]?.id ?? null);
    }).catch(cause => { if (!abort.signal.aborted) setError(`无法连接本地服务：${cause.message}`); });
    return () => abort.abort();
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('study', selectedId);
    window.history.replaceState(null, '', url);
  }, [selectedId]);

  useEffect(() => {
    if (selectedId && !studies.some(study => study.id === selectedId)) {
      setSelectedId(studies.find(study => study.supported)?.id ?? studies[0]?.id ?? null);
    }
  }, [studies, selectedId]);

  useEffect(() => {
    setMeta(null); setVolume(null); setImage(null); setLoadedStudyId(null); setJob(null); setLoading(null);
    if (!selectedId) return;
    setError('');
    if (!selected?.supported) return;
    const abort = new AbortController();
    const id = selectedId;
    setLoading('正在读取影像…');
    async function load() {
      if (!selected!.ready) {
        const queued = await api<Job>(`/studies/${encodeURIComponent(id)}/prepare`, { method: 'POST', signal: abort.signal });
        await waitForJob(queued.id, abort.signal, progress => {
          if (!abort.signal.aborted) { setJob(progress); setLoading(localText(progress.message) || '正在处理影像…'); }
        });
      }
      const data = await api<CtMetadata | XrayMetadata>(`/studies/${encodeURIComponent(id)}/metadata`, { signal: abort.signal });
      if (abort.signal.aborted) return;
      if (selected!.kind === 'ct') {
        const ct = data as CtMetadata;
        setLoading('正在载入 CT 切片…');
        const buffer = await loadGzip(assetUrl(id, 'volume.rawz'), abort.signal);
        if (abort.signal.aborted) return;
        if (buffer.byteLength !== ct.dimensions_xyz.reduce((a, b) => a * b, 1) * 4) throw new Error('CT 体数据尺寸与元数据不一致，无法显示。');
        setMeta(ct); setVolume(new Float32Array(buffer));
      } else setImage(data as XrayMetadata);
      setStudies(previous => previous.map(study => study.id === id ? { ...study, ready: true } : study));
      setLoadedStudyId(id); setLoading(null); setJob(null);
    }
    load().catch(cause => {
      if (!abort.signal.aborted) { setError(cause.message || '暂时无法打开这组影像'); setLoading(null); setJob(null); }
    });
    return () => abort.abort();
    // A study is loaded once on selection; ready updates must not restart its preparation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, reload]);

  async function importFiles(files: FileList | File[]) {
    if (!files.length || importing) return;
    setImporting(true); setError(''); setNotices([]);
    try {
      const body = new FormData();
      Array.from(files).forEach(file => body.append('files', file, file.webkitRelativePath || file.name));
      const result = await api<ImportResult>('/import', { method: 'POST', body });
      setStudies(previous => [...previous.filter(study => !result.studies.some(item => item.id === study.id)), ...result.studies]);
      setNotices(result.warnings || []);
      setSelectedId(result.studies.find(study => study.supported)?.id ?? result.studies[0]?.id ?? null);
      if (!result.studies.length) setError('没有找到可查看的影像。请选择 DICOM、ZIP 或普通图片。');
    } catch (cause) { setError(cause instanceof Error ? cause.message : '导入失败'); }
    finally { setImporting(false); if (filesInput.current) filesInput.current.value = ''; if (folderInput.current) folderInput.current.value = ''; }
  }

  async function loadDemo() {
    if (importing) return;
    setImporting(true); setError(''); setNotices([]);
    try {
      const result = await api<ImportResult>('/demo', { method: 'POST' });
      setStudies(previous => [...previous.filter(study => !result.studies.some(item => item.id === study.id)), ...result.studies]);
      setNotices(result.warnings || []);
      setSelectedId(result.studies.find(study => study.supported)?.id ?? result.studies[0]?.id ?? null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '示例创建失败'); }
    finally { setImporting(false); }
  }

  async function deleteStudy(study: Study) {
    if (!window.confirm('从查看器中删除这组影像及其生成结果？你最初选择的原文件会保留。')) return;
    try {
      await api(`/studies/${encodeURIComponent(study.id)}`, { method: 'DELETE' });
      setStudies(previous => previous.filter(item => item.id !== study.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '删除失败'); }
  }

  return <div className="app" onDragOver={event => { event.preventDefault(); if (!importing) setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); void importFiles(event.dataTransfer.files); }}>
    <input ref={filesInput} className="hidden" type="file" multiple aria-label="选择 DICOM、ZIP 或图片文件" onChange={event => event.target.files && void importFiles(event.target.files)} />
    <input ref={folderInput} className="hidden" type="file" multiple {...{ webkitdirectory: '' }} aria-label="选择 DICOM 文件夹" onChange={event => event.target.files && void importFiles(event.target.files)} />
    <header className="app-header">
      <a className="brand" href="/" aria-label="OpenBone 首页"><span className="brand-symbol"><Bone size={25} strokeWidth={1.8} /></span><span>Open<span className="brand-light">Bone</span><small>自己的影像，慢慢看懂</small></span></a>
      <div className="header-center"><span className="header-dot" /> 为想了解自己影像的你</div>
      <div className="header-actions"><button className="header-help" onClick={() => openHelp('start')}><CircleHelp size={16} /> 看不懂？点这里</button><button className="local-badge" aria-label="了解影像隐私" onClick={() => openHelp('privacy')}><ShieldCheck size={14} /> 只在本机处理</button></div>
    </header>
    <div className="app-body">
      <aside className="sidebar">
        <div className="sidebar-heading"><span>已打开的影像</span><span className="count">{studies.length.toString().padStart(2, '0')}</span></div>
        <button className="button primary import-main" disabled={importing} onClick={() => filesInput.current?.click()}>{importing ? <LoaderCircle className="spin" size={17} /> : <Plus size={18} />} {importing ? '正在导入…' : '打开我的片子'}</button>
        <button className="button subtle folder-button" disabled={importing} onClick={() => folderInput.current?.click()}><FolderOpen size={15} /> 选择整个文件夹</button>
        <div className="study-list">
          {!studies.length && <div className="no-studies"><Layers size={30} strokeWidth={1.2} /><p>还没有打开片子</p><small>医院给的文件或 ZIP 都可以试试</small></div>}
          {studies.map(study => <div className={`study-card ${study.id === selectedId ? 'selected' : ''}`} data-study-id={study.id} key={study.id}>
            <button className="study-select" onClick={() => setSelectedId(study.id)}>
              <span className={`study-icon ${study.kind}`}>{study.kind === 'ct' ? <ScanLine size={20} /> : <FileImage size={20} />}</span>
              <span className="study-copy"><strong>{studyLabel(study)}</strong><span>{study.kind === 'ct' ? `${study.count} 张切片` : '二维图片'}</span><small className={!study.supported ? 'unsupported' : ''}>{!study.supported ? '暂时无法查看' : study.ready ? '可以查看' : '点击后准备'}</small></span>
              {study.id === selectedId && <ChevronRight size={15} className="study-chevron" />}
            </button>
            <button className="delete-study" aria-label={`删除${studyLabel(study)}`} title="从查看器删除这组影像" onClick={() => void deleteStudy(study)}><Trash2 size={14} /></button>
          </div>)}
        </div>
        <button className="demo-link" disabled={importing} onClick={() => void loadDemo()}><FlaskConical size={16} /><span>打开合成示例</span><ArrowUpRight size={14} /></button>
        <button className="sidebar-help" onClick={() => openHelp('start')}>该选哪个文件？为什么有好几组？</button>
        <details className="support-info"><summary>哪些文件可以打开？</summary><p>医院给的 CT / X 光 DICOM 文件、文件夹或 ZIP，以及 PNG / JPEG / WebP / BMP 图片。三维需要完整 CT 切片，单张截图只能当图片看。</p><p>部分扫描格式首版暂不支持，打不开时会说明原因。</p></details>
        <div className="sidebar-bottom"><HardDrive size={15} /><span>影像保存在本机<br /><small>合成示例是人工图形，并非患者影像</small></span></div>
      </aside>
      <main className="main-workspace">
        {error && <div className="notice error" role="alert"><AlertTriangle size={18} /><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}><X size={16} /></button></div>}
        {notices.length > 0 && <div className="notice warning"><AlertTriangle size={17} /><div>{notices.map((notice, index) => <p key={index}>{localText(notice)}</p>)}</div><button aria-label="关闭导入提示" onClick={() => setNotices([])}><X size={16} /></button></div>}
        {selected ? <>
          <div className="workspace-heading"><div><div className="eyebrow">{selected.kind === 'ct' ? '逐层看，也能立体看' : '放大看看自己的片子'}</div><h1>{studyLabel(selected)}</h1><p>{selected.kind === 'ct' ? '先了解方向与形状，再对照报告整理自己的疑问。' : '拖动移动，滚轮放大；想调明暗时，展开下方设置。'}</p></div><span className="data-badge"><span /> 仅本机查看</span></div>
          {!selected.supported ? <div className="unsupported-state"><AlertTriangle size={35} /><h2>这组影像暂时打不开</h2><p>{localText(selected.reason || '当前版本还不能正确显示这种影像格式。')}</p><p>这是软件支持范围的提示，不是病情判断。</p><button className="button secondary" onClick={() => openHelp('start')}><CircleHelp size={15} /> 查看打不开的常见原因</button><button className="button subtle" onClick={() => filesInput.current?.click()}>打开其他影像</button></div>
          : loading || (loadedStudyId !== selectedId && !error) ? <div className="loading-state" role="status"><div className="loading-scan"><ScanLine size={40} /><span /></div><h2>{loading || '正在读取影像…'}</h2><p>{job?.status === 'queued' ? '正在等待本机处理，请稍候。' : '正在这台电脑上准备画面，完整 CT 可能需要一些时间。'}</p><div className="indeterminate"><span /></div></div>
          : loadedStudyId === selectedId && meta && volume ? <CtViewer key={selected.id} studyId={selected.id} meta={meta} volume={volume} onModel={model => setMeta(previous => previous ? { ...previous, models: [...previous.models.filter(item => item.mesh_file !== model.mesh_file), model] } : previous)} />
          : loadedStudyId === selectedId && image ? <XrayViewer key={selected.id} studyId={selected.id} image={image} />
          : error ? <div className="retry-area"><button className="button secondary" onClick={() => setReload(value => value + 1)}>重新打开这组影像</button></div> : null}
        </> : <div className="welcome">
          <div className="welcome-topline"><span className="tiny-label">免费开源 · 在自己电脑上看片</span><span className="fine-rule" /></div>
          <div className="welcome-layout"><div className="welcome-copy"><div className="eyebrow">给想了解自己病情的你</div><h1>自己的片子，<br /><em>看得更明白。</em></h1><p className="welcome-intro">拿到医院的 CT 或 X 光，却不知道从哪看起？<br />打开片子，认识方向，转动三维，一步步了解画面。</p><div className="welcome-buttons"><button className="button primary large" disabled={importing} onClick={() => filesInput.current?.click()}><Upload size={18} /> 打开我的片子 <ArrowUpRight size={17} /></button><button className="button secondary large" disabled={importing} onClick={() => void loadDemo()}><FlaskConical size={17} /> 先试试合成示例</button></div><div className="drop-note"><FolderOpen size={15} /> 把医院给的文件、文件夹或 ZIP 选进来；也可以拖入文件</div><button className="welcome-help" onClick={() => openHelp('start')}><CircleHelp size={16} /> 第一次用？看看从哪里开始</button></div><div className="welcome-art" aria-hidden="true"><div className="art-grid"><div className="phantom-panel"><span>横着看</span><div className="phantom axial" /><i /><b /></div><div className="phantom-panel"><span>正面看</span><div className="phantom coronal" /><i /><b /></div><div className="phantom-panel"><span>侧面看</span><div className="phantom sagittal" /><i /><b /></div><div className="phantom-panel three-illustration"><Box size={67} strokeWidth={0.65} /><span>立体看</span></div></div><div className="art-caption"><span className="green-dot" /> 同一个部位，不同方向<span>人工示意画面</span></div></div></div>
          <div className="feature-row"><div><span className="feature-number">01</span><div><h3>一层层，慢慢看</h3><p>从三个方向找到同一个位置。</p></div></div><div><span className="feature-number">02</span><div><h3>转一转，认识外形</h3><p>把 CT 变成立体画面，更容易理解形状。</p></div></div><div><span className="feature-number">03</span><div><h3>不懂时，随时查</h3><p>画面旁有答疑，操作和常见疑问都有说明。</p></div></div></div>
          <div className="welcome-footer"><ShieldCheck size={17} /><p>无需账号，影像在本机处理。帮助你理解画面、整理疑问；具体病情仍需结合检查报告和医生评估。</p></div>
        </div>}
      </main>
    </div>
    {dragging && <div className="drop-overlay"><Upload size={40} /><strong>放开以导入影像</strong><span>DICOM · ZIP · 普通图片</span></div>}
  </div>;
}
