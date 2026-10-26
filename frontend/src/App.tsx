import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowUpRight, Bone, Box, ChevronRight, FileImage, FlaskConical, FolderOpen, HardDrive, Layers, LoaderCircle, Plus, ScanLine, ShieldCheck, Trash2, Upload, X } from 'lucide-react';
import { CtViewer } from './CtViewer';
import { XrayViewer } from './XrayViewer';
import { api, assetUrl, loadGzip, localText, studyLabel, waitForJob } from './types';
import type { CtMetadata, Job, Study, XrayMetadata } from './types';

type ImportResult = { studies: Study[]; warnings: string[] };

export function App() {
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
    setLoading('正在读取检查…');
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
        setLoading('正在载入原始 HU 体数据…');
        const buffer = await loadGzip(assetUrl(id, 'volume.rawz'), abort.signal);
        if (abort.signal.aborted) return;
        if (buffer.byteLength !== ct.dimensions_xyz.reduce((a, b) => a * b, 1) * 4) throw new Error('CT 体数据尺寸与元数据不一致，无法显示。');
        setMeta(ct); setVolume(new Float32Array(buffer));
      } else setImage(data as XrayMetadata);
      setStudies(previous => previous.map(study => study.id === id ? { ...study, ready: true } : study));
      setLoadedStudyId(id); setLoading(null); setJob(null);
    }
    load().catch(cause => {
      if (!abort.signal.aborted) { setError(cause.message || '无法打开这次检查'); setLoading(null); setJob(null); }
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
    if (!window.confirm('删除这次检查及其本地生成的数据？原始导入文件不会从您的电脑中移除。')) return;
    try {
      await api(`/studies/${encodeURIComponent(study.id)}`, { method: 'DELETE' });
      setStudies(previous => previous.filter(item => item.id !== study.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : '删除失败'); }
  }

  return <div className="app" onDragOver={event => { event.preventDefault(); if (!importing) setDragging(true); }} onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false); }} onDrop={event => { event.preventDefault(); setDragging(false); void importFiles(event.dataTransfer.files); }}>
    <input ref={filesInput} className="hidden" type="file" multiple aria-label="选择 DICOM、ZIP 或图片文件" onChange={event => event.target.files && void importFiles(event.target.files)} />
    <input ref={folderInput} className="hidden" type="file" multiple {...{ webkitdirectory: '' }} aria-label="选择 DICOM 文件夹" onChange={event => event.target.files && void importFiles(event.target.files)} />
    <header className="app-header">
      <a className="brand" href="/" aria-label="OpenBone 首页"><span className="brand-symbol"><Bone size={25} strokeWidth={1.8} /></span><span>Open<span className="brand-light">Bone</span><small>影像工作台</small></span></a>
      <nav className="header-center"><span className="header-dot" /> 本地影像，清楚看见</nav>
      <div className="header-actions"><span className="local-badge"><ShieldCheck size={14} /> 本地处理</span><span className="version">v0.1.0</span></div>
    </header>
    <div className="app-body">
      <aside className="sidebar">
        <div className="sidebar-heading"><span>我的检查</span><span className="count">{studies.length.toString().padStart(2, '0')}</span></div>
        <button className="button primary import-main" disabled={importing} onClick={() => filesInput.current?.click()}>{importing ? <LoaderCircle className="spin" size={17} /> : <Plus size={18} />} {importing ? '正在导入…' : '导入影像'}</button>
        <button className="button subtle folder-button" disabled={importing} onClick={() => folderInput.current?.click()}><FolderOpen size={15} /> 选择整个文件夹</button>
        <div className="study-list">
          {!studies.length && <div className="no-studies"><Layers size={30} strokeWidth={1.2} /><p>还没有检查</p><small>导入后，检查将出现在这里</small></div>}
          {studies.map(study => <div className={`study-card ${study.id === selectedId ? 'selected' : ''}`} data-study-id={study.id} key={study.id}>
            <button className="study-select" onClick={() => setSelectedId(study.id)}>
              <span className={`study-icon ${study.kind}`}>{study.kind === 'ct' ? <ScanLine size={20} /> : <FileImage size={20} />}</span>
              <span className="study-copy"><strong>{studyLabel(study)}</strong><span>{study.modality || study.kind.toUpperCase()} · {study.kind === 'ct' ? `${study.count} 层` : `${study.columns} × ${study.rows}`}</span><small className={!study.supported ? 'unsupported' : ''}>{!study.supported ? '暂不支持' : study.ready ? '已就绪' : '待处理'}</small></span>
              {study.id === selectedId && <ChevronRight size={15} className="study-chevron" />}
            </button>
            <button className="delete-study" aria-label={`删除${studyLabel(study)}`} title="删除这次检查" onClick={() => void deleteStudy(study)}><Trash2 size={14} /></button>
          </div>)}
        </div>
        <button className="demo-link" disabled={importing} onClick={() => void loadDemo()}><FlaskConical size={16} /><span>打开合成示例</span><ArrowUpRight size={14} /></button>
        <details className="support-info"><summary>支持哪些影像？</summary><p>常规单帧 CT DICOM、DICOM X 光及 PNG / JPEG / WebP / BMP 图片。可选择多个文件、文件夹或 ZIP。</p><p>首版对斜位、机架倾斜、非均匀层距和多帧 CT 明确提示不支持。</p></details>
        <div className="sidebar-bottom"><HardDrive size={15} /><span>影像保存在本机<br /><small>软件不上传到云端</small></span></div>
      </aside>
      <main className="main-workspace">
        {error && <div className="notice error" role="alert"><AlertTriangle size={18} /><span>{error}</span><button aria-label="关闭错误提示" onClick={() => setError('')}><X size={16} /></button></div>}
        {notices.length > 0 && <div className="notice warning"><AlertTriangle size={17} /><div>{notices.map((notice, index) => <p key={index}>{localText(notice)}</p>)}</div><button aria-label="关闭导入提示" onClick={() => setNotices([])}><X size={16} /></button></div>}
        {selected ? <>
          <div className="workspace-heading"><div><div className="eyebrow">{selected.kind === 'ct' ? 'CT WORKSPACE' : 'IMAGE WORKSPACE'}</div><h1>{studyLabel(selected)}</h1><p>{selected.kind === 'ct' ? '从原始切片到三维形态，在一个工作台中查看。' : '打开影像，自由缩放，调整显示。'}</p></div><span className="data-badge"><span /> {selected.kind === 'ct' ? 'CT 检查' : '二维影像'}</span></div>
          {!selected.supported ? <div className="unsupported-state"><AlertTriangle size={35} /><h2>这组影像暂不支持</h2><p>{localText(selected.reason || '影像格式或几何超出了首版的支持范围。')}</p><button className="button secondary" onClick={() => filesInput.current?.click()}>导入其他影像</button></div>
          : loading || (loadedStudyId !== selectedId && !error) ? <div className="loading-state" role="status"><div className="loading-scan"><ScanLine size={40} /><span /></div><h2>{loading || '正在读取检查…'}</h2><p>{job?.status === 'queued' ? '检查已进入本地处理队列，请稍候。' : '解码与三维数据准备在本机完成。较大的检查可能需要一些时间。'}</p><div className="indeterminate"><span /></div></div>
          : loadedStudyId === selectedId && meta && volume ? <CtViewer key={selected.id} studyId={selected.id} meta={meta} volume={volume} onModel={model => setMeta(previous => previous ? { ...previous, models: [...previous.models.filter(item => item.mesh_file !== model.mesh_file), model] } : previous)} />
          : loadedStudyId === selectedId && image ? <XrayViewer key={selected.id} studyId={selected.id} image={image} />
          : error ? <div className="retry-area"><button className="button secondary" onClick={() => setReload(value => value + 1)}>重新打开这次检查</button></div> : null}
        </> : <div className="welcome">
          <div className="welcome-topline"><span className="tiny-label">OPEN SOURCE · LOCAL FIRST</span><span className="fine-rule" /></div>
          <div className="welcome-layout"><div className="welcome-copy"><div className="eyebrow">为每一份影像，打开一个视角</div><h1>自己的片子，<br /><em>看得更明白。</em></h1><p className="welcome-intro">轻量、开源的 CT 与 X 光查看器。<br />导入本地影像，联动浏览切片，探索三维形态。</p><div className="welcome-buttons"><button className="button primary large" disabled={importing} onClick={() => filesInput.current?.click()}><Upload size={18} /> 导入影像 <ArrowUpRight size={17} /></button><button className="button secondary large" disabled={importing} onClick={() => void loadDemo()}><FlaskConical size={17} /> 先试试合成示例</button></div><div className="drop-note"><FolderOpen size={15} /> 也可以将 DICOM、ZIP 或图片拖到这里</div></div><div className="welcome-art" aria-hidden="true"><div className="art-grid"><div className="phantom-panel"><span>AXIAL</span><div className="phantom axial" /><i /><b /></div><div className="phantom-panel"><span>CORONAL</span><div className="phantom coronal" /><i /><b /></div><div className="phantom-panel"><span>SAGITTAL</span><div className="phantom sagittal" /><i /><b /></div><div className="phantom-panel three-illustration"><Box size={67} strokeWidth={0.65} /><span>3D VIEW</span></div></div><div className="art-caption"><span className="green-dot" /> 二维与三维，连在一起<span>示意画面</span></div></div></div>
          <div className="feature-row"><div><span className="feature-number">01</span><div><h3>多平面联动</h3><p>横断、冠状、矢状位同步定位。</p></div></div><div><span className="feature-number">02</span><div><h3>三维探索</h3><p>体绘制、阈值表面与 STL 导出。</p></div></div><div><span className="feature-number">03</span><div><h3>在本机完成</h3><p>无需账户，不上传个人影像。</p></div></div></div>
          <div className="welcome-footer"><ShieldCheck size={17} /><p>用于个人查看与学习。三维显示和阈值表面不能替代原始影像或专业诊断。</p></div>
        </div>}
      </main>
    </div>
    {dragging && <div className="drop-overlay"><Upload size={40} /><strong>放开以导入影像</strong><span>DICOM · ZIP · 普通图片</span></div>}
  </div>;
}
