import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Box, CircleHelp, Crosshair, Download, Layers3, LoaderCircle, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { FullscreenButton } from './FullscreenButton';
import { useHelp } from './HelpContext';
import { SlicePanel, planes } from './SlicePanel';
import { api, assetUrl, clamp, localText, voxelValue, waitForJob } from './types';
import type { CtMetadata, Job, SurfaceModel, XYZ } from './types';
import './patient-viewer.css';

const ThreeScene = lazy(() => import('./ThreeScene').then(module => ({ default: module.ThreeScene })));

export function CtViewer({ studyId, meta, volume, onModel }: { studyId: string; meta: CtMetadata; volume: Float32Array; onModel: (model: SurfaceModel) => void }) {
  const { openHelp } = useHelp();
  const [point, setPoint] = useState<XYZ>(() => meta.dimensions_xyz.map(n => Math.floor(n / 2)) as XYZ);
  const [center, setCenter] = useState(500);
  const [width, setWidth] = useState(1800);
  const [threshold, setThreshold] = useState(300);
  const [mode, setMode] = useState<'volume' | 'surface'>('volume');
  const [bodyPreview, setBodyPreview] = useState(() => Boolean(meta.body_volume_rendering));
  const [smooth, setSmooth] = useState(false);
  const [model, setModel] = useState<SurfaceModel | undefined>(() => meta.models.at(-1));
  const [meshMessage, setMeshMessage] = useState('');
  const [meshError, setMeshError] = useState('');
  const [reset, setReset] = useState(0);
  const [roiEnabled, setRoiEnabled] = useState(false);
  const [roi, setRoi] = useState<number[]>([0, meta.dimensions_xyz[0] - 1, 0, meta.dimensions_xyz[1] - 1, 0, meta.dimensions_xyz[2] - 1]);
  const abort = useRef<AbortController | null>(null);
  const threePanel = useRef<HTMLElement>(null);
  const advancedPanel = useRef<HTMLDetailsElement>(null);
  const fullRoi = [0, meta.dimensions_xyz[0] - 1, 0, meta.dimensions_xyz[1] - 1, 0, meta.dimensions_xyz[2] - 1];
  const requestedRoi = roiEnabled ? roi : fullRoi;
  const modelMatches = Boolean(model && model.threshold_hu === threshold && Boolean(model.smoothing) === smooth && (model.roi || fullRoi).every((value, index) => value === requestedRoi[index]));
  const displayMeta = useMemo(() => ({ ...meta, volume_rendering: bodyPreview && meta.body_volume_rendering ? meta.body_volume_rendering : meta.volume_rendering }), [meta, bodyPreview]);
  useEffect(() => () => abort.current?.abort(), []);

  function showModelSettings() {
    if (!advancedPanel.current) return;
    advancedPanel.current.open = true;
    advancedPanel.current.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    advancedPanel.current.querySelector('summary')?.focus();
  }

  async function generateModel() {
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    setMeshError(''); setMeshMessage('正在准备生成三维表面…');
    try {
      const queued = await api<Job>(`/studies/${encodeURIComponent(studyId)}/mesh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threshold, smooth, ...(roiEnabled ? { roi } : {}) }), signal: controller.signal });
      const completed = await waitForJob(queued.id, controller.signal, progress => { if (!controller.signal.aborted) setMeshMessage(localText(progress.message) || '正在生成三维表面…'); });
      if (controller.signal.aborted) return;
      const result = completed.result?.model;
      if (!result) throw new Error('生成完成，但没有返回表面模型。');
      setModel(result); onModel(result); setMode('surface'); setMeshMessage(''); setReset(value => value + 1);
    } catch (cause) { if (!controller.signal.aborted) { setMeshError(cause instanceof Error ? cause.message : '模型生成失败'); setMeshMessage(''); } }
  }

  return <div className="ct-workspace">
    <div className="viewer-introduction"><div><strong>同一处身体，从三个方向看</strong><p>拖动下方滑条逐层翻看；点一下画面，另外两张切片会对准同一位置。</p></div><button className="viewer-help-button" onClick={() => openHelp('ct')}><CircleHelp size={16} /> 这几个画面怎么看？</button></div>
    <div className="ct-toolbar patient-ct-toolbar"><div className="toolbar-label"><Crosshair size={16} /><span>想突出哪类结构？</span></div><div className="preset-buttons" role="group" aria-label="切片显示预设">{[{ label: '看骨骼', center: 500, width: 1800 }, { label: '看软组织', center: 40, width: 400 }, { label: '看肺部', center: -600, width: 1500 }].map(preset => <button key={preset.label} aria-pressed={center === preset.center && width === preset.width} className={center === preset.center && width === preset.width ? 'active' : ''} onClick={() => { setCenter(preset.center); setWidth(preset.width); }}>{preset.label}</button>)}</div><span className="viewer-toolbar-note">只调整明暗，原始数据不变</span></div>
    <div className="views-grid">
      {planes.map(plane => <SlicePanel key={plane.axis} plane={plane} meta={meta} volume={volume} point={point} onPoint={setPoint} center={center} width={width} />)}
      <section className="view-panel three-panel" ref={threePanel}>
        <div className="panel-heading"><div><span className="plane-dot three-dot" /><strong>立体看外形</strong><span className="panel-code">三维</span></div><div className="panel-actions"><button className="viewer-help-button dark" onClick={() => openHelp('three')}><CircleHelp size={13} /> 三维怎么看？</button><button className="icon-button" title="恢复三维初始视角" aria-label="重置三维视角" onClick={() => setReset(value => value + 1)}><RotateCcw size={15} /></button><FullscreenButton target={threePanel} label="三维视图" /></div></div>
        <div className="three-mode-tabs" role="group" aria-label="三维显示方式"><button aria-pressed={mode === 'volume'} className={mode === 'volume' ? 'active' : ''} onClick={() => setMode('volume')}><Layers3 size={13} /> 三维外观</button><button aria-pressed={mode === 'surface'} className={mode === 'surface' ? 'active' : ''} onClick={() => setMode('surface')}><Box size={13} /> 表面模型</button><span>帮助理解整体外形</span></div>
        {mode === 'volume' && meta.body_volume_rendering && <div className="volume-preview-options"><div role="group" aria-label="体绘制结构范围"><button className={bodyPreview ? 'active' : ''} aria-pressed={bodyPreview} onClick={() => setBodyPreview(true)}>主体预览</button><button className={!bodyPreview ? 'active' : ''} aria-pressed={!bodyPreview} onClick={() => setBodyPreview(false)}>全部结构</button></div><span>主体预览会隐藏部分分离结构，可切换对照；相连的支架仍可能保留</span></div>}
        <div className="three-viewport">{mode === 'surface' && !model ? <div className="surface-empty"><Box size={30} strokeWidth={1} /><strong>还没有生成表面模型</strong><p>先看“三维外观”即可浏览。<br />想导出模型，可展开下方设置再生成。</p><button className="viewer-help-button dark" onClick={showModelSettings}>打开模型生成设置</button></div> : <Suspense fallback={<div className="view-message">正在载入三维显示模块…</div>}><ThreeScene key={`${studyId}-${mode}`} studyId={studyId} meta={mode === 'volume' ? displayMeta : meta} mode={mode} threshold={threshold} model={model} resetKey={reset} /></Suspense>}</div>
        <div className="three-footer"><span>拖动旋转 · 右键平移 · 滚轮缩放</span><span>{mode === 'surface' ? !model ? '等待生成模型' : modelMatches ? '按当前设置生成' : '上次生成的模型' : '从 CT 生成的外观'}</span></div>
      </section>
    </div>
    <div className="simple-threshold"><div><label htmlFor="threshold">三维里保留多少结构</label><p>{mode === 'volume' ? '向左显示更多，向右更突出高密度结构。若某处消失，先调回去并对照切片。' : '当前选的是表面模型。调整后需在“更多调整与导出”里重新生成。'}</p></div><div className="simple-threshold-slider"><span>更多结构</span><input id="threshold" aria-label="三维结构显示阈值" type="range" min={-1000} max={3000} step={10} value={threshold} onChange={event => setThreshold(Number(event.target.value))} /><span>更少结构</span></div></div>
    <details className="viewer-advanced" ref={advancedPanel}>
      <summary><SlidersHorizontal size={16} /><span>更多调整与导出</span><small>明暗数值、模型生成、数据下载</small></summary>
      <div className="viewer-advanced-content">
        <section className="advanced-display-controls" aria-label="切片明暗数值"><div><h2>细调切片的明暗</h2><p>“窗位”和“窗宽”是影像的显示参数，只改变哪些灰度更容易看清。</p></div><label className="window-control">窗位 <input aria-label="窗位 HU" type="number" min={-5000} max={10000} value={center} onChange={event => setCenter(clamp(Number(event.target.value), -5000, 10000))} /><span>HU</span></label><label className="window-control">窗宽 <input aria-label="窗宽 HU" type="number" min={1} max={20000} value={width} onChange={event => setWidth(clamp(Number(event.target.value), 1, 20000))} /><span>HU</span></label><a className="button subtle download-nrrd" href={assetUrl(studyId, 'source.nrrd')} download><Download size={15} /> 下载原始数据 NRRD</a></section>
        <div className="position-readout"><span><Crosshair size={13} /> 当前选中位置</span><code>X {point[0]} · Y {point[1]} · Z {point[2]}</code><span className="hu-readout">{voxelValue(volume, meta.dimensions_xyz, point).toFixed(1)} HU</span><span className="geometry-readout">数据大小 {meta.dimensions_xyz.join(' × ')} 体素 · 间距 {meta.spacing_xyz_mm.map(n => n.toFixed(2)).join(' × ')} mm</span></div>
    <section className="model-controls"><div className="model-control-heading"><div><Box size={19} /><div><h2>生成可导出的三维表面</h2><p>按密度筛选并提取表面，可能包含多块骨骼、石膏或扫描支架，不会自动分离一块骨头。{meta.body_volume_rendering && '“主体预览”不影响这里的模型和导出。'}</p></div></div><a className={`button secondary small ${!modelMatches || meshMessage ? 'disabled-link' : ''}`} href={model && modelMatches && !meshMessage ? assetUrl(studyId, model.stl_file) : undefined} aria-disabled={!modelMatches || Boolean(meshMessage)} title={!modelMatches ? '请先按当前密度阈值、平滑和范围设置生成表面' : '下载当前设置的 STL 表面，单位毫米'} download><Download size={14} /> 导出 STL</a></div>
      <div className="threshold-controls"><label className="number-unit">密度阈值 <input aria-label="阈值 HU" type="number" min={-1000} max={3000} value={threshold} onChange={event => setThreshold(clamp(Number(event.target.value), -1000, 3000))} /> HU</label><label className="checkbox-label"><input type="checkbox" checked={smooth} onChange={event => setSmooth(event.target.checked)} /> 让表面更平滑</label><button className="button primary" disabled={Boolean(meshMessage)} onClick={() => void generateModel()}>{meshMessage ? <LoaderCircle className="spin" size={15} /> : <Box size={15} />} {meshMessage ? '正在生成…' : '生成表面模型'}</button></div>
      <div className="roi-controls"><label className="checkbox-label"><input type="checkbox" checked={roiEnabled} onChange={event => setRoiEnabled(event.target.checked)} /> 只生成选定范围（ROI）</label>{roiEnabled && <div className="roi-ranges">{['X', 'Y', 'Z'].map((axis, i) => <label key={axis}>{axis}<input aria-label={`${axis}最小体素`} type="number" min={0} max={roi[i * 2 + 1]} value={roi[i * 2]} onChange={event => setRoi(previous => { const next = [...previous]; next[i * 2] = clamp(Math.round(Number(event.target.value)), 0, next[i * 2 + 1]); return next; })} /><span>—</span><input aria-label={`${axis}最大体素`} type="number" min={roi[i * 2]} max={meta.dimensions_xyz[i] - 1} value={roi[i * 2 + 1]} onChange={event => setRoi(previous => { const next = [...previous]; next[i * 2 + 1] = clamp(Math.round(Number(event.target.value)), next[i * 2], meta.dimensions_xyz[i] - 1); return next; })} /></label>)}</div>}</div>
      {meshMessage && <div className="mesh-progress" role="status"><LoaderCircle size={13} className="spin" />{meshMessage}</div>}{meshError && <div className="notice error compact" role="alert"><AlertTriangle size={15} />{meshError}</div>}
      {model && <p className="model-details">当前表面：{model.threshold_hu} HU · {model.smoothing ? '已平滑，仅供显示' : '未平滑'} · {model.roi ? `选定范围 ${model.roi.join(', ')}` : '全部扫描范围'} · {model.triangles.toLocaleString()} 个三角面 · STL 单位 mm。改变设置后需重新生成。</p>}
      {model && !modelMatches && <p className="mesh-progress"><AlertTriangle size={13} /> 设置已改变，目前仍是上次生成的模型。请重新生成后导出。</p>}
    </section>
        {Boolean(meta.warnings?.length) && <details className="ct-data-details"><summary><AlertTriangle size={14} /> 原始数据与三维显示说明</summary><div>{meta.warnings?.map((warning, i) => <p key={i}>{localText(warning)}</p>)}</div></details>}
      </div>
    </details>
    <p className="data-note"><span /> 三维外观会随显示设置变化；看到凹凸、空隙或断开时，请回到切片对照。这个工具帮助理解影像，不能据此判断病情、愈合程度或活动是否安全。</p>
  </div>;
}
