import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Box, Crosshair, Download, Layers3, LoaderCircle, RotateCcw } from 'lucide-react';
import { FullscreenButton } from './FullscreenButton';
import { SlicePanel, planes } from './SlicePanel';
import { api, assetUrl, clamp, localText, voxelValue, waitForJob } from './types';
import type { CtMetadata, Job, SurfaceModel, XYZ } from './types';

const ThreeScene = lazy(() => import('./ThreeScene').then(module => ({ default: module.ThreeScene })));

export function CtViewer({ studyId, meta, volume, onModel }: { studyId: string; meta: CtMetadata; volume: Float32Array; onModel: (model: SurfaceModel) => void }) {
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
  const fullRoi = [0, meta.dimensions_xyz[0] - 1, 0, meta.dimensions_xyz[1] - 1, 0, meta.dimensions_xyz[2] - 1];
  const requestedRoi = roiEnabled ? roi : fullRoi;
  const modelMatches = Boolean(model && model.threshold_hu === threshold && Boolean(model.smoothing) === smooth && (model.roi || fullRoi).every((value, index) => value === requestedRoi[index]));
  const displayMeta = useMemo(() => ({ ...meta, volume_rendering: bodyPreview && meta.body_volume_rendering ? meta.body_volume_rendering : meta.volume_rendering }), [meta, bodyPreview]);
  useEffect(() => () => abort.current?.abort(), []);

  async function generateModel() {
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    setMeshError(''); setMeshMessage('正在提交表面生成任务…');
    try {
      const queued = await api<Job>(`/studies/${encodeURIComponent(studyId)}/mesh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ threshold, smooth, ...(roiEnabled ? { roi } : {}) }), signal: controller.signal });
      const completed = await waitForJob(queued.id, controller.signal, progress => { if (!controller.signal.aborted) setMeshMessage(localText(progress.message) || '正在生成阈值表面…'); });
      if (controller.signal.aborted) return;
      const result = completed.result?.model;
      if (!result) throw new Error('生成完成，但没有返回表面模型。');
      setModel(result); onModel(result); setMode('surface'); setMeshMessage(''); setReset(value => value + 1);
    } catch (cause) { if (!controller.signal.aborted) { setMeshError(cause instanceof Error ? cause.message : '模型生成失败'); setMeshMessage(''); } }
  }

  return <div className="ct-workspace">
    <div className="ct-toolbar"><div className="toolbar-label"><Crosshair size={16} /><span>联动切片</span></div><div className="preset-buttons">{[{ label: '骨窗', center: 500, width: 1800 }, { label: '软组织', center: 40, width: 400 }, { label: '肺窗', center: -600, width: 1500 }].map(preset => <button key={preset.label} className={center === preset.center && width === preset.width ? 'active' : ''} onClick={() => { setCenter(preset.center); setWidth(preset.width); }}>{preset.label}</button>)}</div><label className="window-control">窗位 <input aria-label="窗位 HU" type="number" min={-5000} max={10000} value={center} onChange={event => setCenter(clamp(Number(event.target.value), -5000, 10000))} /><span>HU</span></label><label className="window-control">窗宽 <input aria-label="窗宽 HU" type="number" min={1} max={20000} value={width} onChange={event => setWidth(clamp(Number(event.target.value), 1, 20000))} /><span>HU</span></label><a className="button subtle download-nrrd" href={assetUrl(studyId, 'source.nrrd')} download><Download size={15} /> 原始 NRRD</a></div>
    {Boolean(meta.warnings?.length) && <details className="ct-data-details"><summary><AlertTriangle size={14} /> 原始数据与三维显示说明</summary><div>{meta.warnings?.map((warning, i) => <p key={i}>{localText(warning)}</p>)}</div></details>}
    <div className="views-grid">
      {planes.map(plane => <SlicePanel key={plane.axis} plane={plane} meta={meta} volume={volume} point={point} onPoint={setPoint} center={center} width={width} />)}
      <section className="view-panel three-panel" ref={threePanel}>
        <div className="panel-heading"><div><span className="plane-dot three-dot" /><strong>三维视图</strong><span className="panel-code">3D</span></div><div className="panel-actions"><button className="icon-button" title="重置三维视角" aria-label="重置三维视角" onClick={() => setReset(value => value + 1)}><RotateCcw size={15} /></button><FullscreenButton target={threePanel} label="三维视图" /></div></div>
        <div className="three-mode-tabs"><button className={mode === 'volume' ? 'active' : ''} onClick={() => setMode('volume')}><Layers3 size={13} /> 体绘制</button><button className={mode === 'surface' ? 'active' : ''} onClick={() => setMode('surface')}><Box size={13} /> 阈值表面</button><span>显示用派生数据</span></div>
        {mode === 'volume' && meta.body_volume_rendering && <div className="volume-preview-options"><div role="group" aria-label="体绘制结构范围"><button className={bodyPreview ? 'active' : ''} aria-pressed={bodyPreview} onClick={() => setBodyPreview(true)}>主体预览</button><button className={!bodyPreview ? 'active' : ''} aria-pressed={!bodyPreview} onClick={() => setBodyPreview(false)}>全部结构</button></div><span>可能隐藏分离部位，仅影响三维显示</span></div>}
        <div className="three-viewport">{mode === 'surface' && !model ? <div className="surface-empty"><Box size={34} strokeWidth={1} /><strong>生成一个阈值表面</strong><p>在下方设定 HU 阈值并点击生成。<br />结果包含阈值范围内的所有结构。</p></div> : <Suspense fallback={<div className="view-message">正在载入三维显示模块…</div>}><ThreeScene key={`${studyId}-${mode}`} studyId={studyId} meta={mode === 'volume' ? displayMeta : meta} mode={mode} threshold={threshold} model={model} resetKey={reset} /></Suspense>}</div>
        <div className="three-footer"><span>拖动旋转 · 右键平移 · 滚轮缩放</span><span>{mode === 'surface' && model ? `${model.threshold_hu} HU · ${model.triangles.toLocaleString()} 面` : 'GPU · 阈值体绘制'}</span></div>
      </section>
    </div>
    <div className="position-readout"><span><Crosshair size={13} /> 联动位置</span><code>X {point[0]} · Y {point[1]} · Z {point[2]}</code><span className="hu-readout">{voxelValue(volume, meta.dimensions_xyz, point).toFixed(1)} HU</span><span className="geometry-readout">{meta.dimensions_xyz.join(' × ')} voxels · {meta.spacing_xyz_mm.map(n => n.toFixed(2)).join(' × ')} mm</span></div>
    <section className="model-controls"><div className="model-control-heading"><div><Box size={19} /><div><h2>阈值表面与导出</h2><p>提取达到阈值的结构。可限制范围，不等于自动单骨分割。{meta.body_volume_rendering && '主体预览不参与表面生成与 STL 导出。'}</p></div></div><a className={`button secondary small ${!modelMatches || meshMessage ? 'disabled-link' : ''}`} href={model && modelMatches && !meshMessage ? assetUrl(studyId, model.stl_file) : undefined} aria-disabled={!modelMatches || Boolean(meshMessage)} title={!modelMatches ? '请先按当前阈值、平滑和 ROI 生成表面' : '下载当前参数的 STL 表面（mm）'} download><Download size={14} /> 导出 STL</a></div>
      <div className="threshold-controls"><label htmlFor="threshold">显示 / 生成阈值</label><input id="threshold" type="range" min={-1000} max={3000} step={10} value={threshold} onChange={event => setThreshold(Number(event.target.value))} /><label className="number-unit"><input aria-label="阈值 HU" type="number" min={-1000} max={3000} value={threshold} onChange={event => setThreshold(clamp(Number(event.target.value), -1000, 3000))} /> HU</label><label className="checkbox-label"><input type="checkbox" checked={smooth} onChange={event => setSmooth(event.target.checked)} /> 表面平滑</label><button className="button primary" disabled={Boolean(meshMessage)} onClick={() => void generateModel()}>{meshMessage ? <LoaderCircle className="spin" size={15} /> : <Box size={15} />} {meshMessage ? '正在生成…' : '生成阈值表面'}</button></div>
      <div className="roi-controls"><label className="checkbox-label"><input type="checkbox" checked={roiEnabled} onChange={event => setRoiEnabled(event.target.checked)} /> 限制生成范围（体素 ROI）</label>{roiEnabled && <div className="roi-ranges">{['X', 'Y', 'Z'].map((axis, i) => <label key={axis}>{axis}<input aria-label={`${axis}最小体素`} type="number" min={0} max={roi[i * 2 + 1]} value={roi[i * 2]} onChange={event => setRoi(previous => { const next = [...previous]; next[i * 2] = clamp(Math.round(Number(event.target.value)), 0, next[i * 2 + 1]); return next; })} /><span>—</span><input aria-label={`${axis}最大体素`} type="number" min={roi[i * 2]} max={meta.dimensions_xyz[i] - 1} value={roi[i * 2 + 1]} onChange={event => setRoi(previous => { const next = [...previous]; next[i * 2 + 1] = clamp(Math.round(Number(event.target.value)), next[i * 2], meta.dimensions_xyz[i] - 1); return next; })} /></label>)}</div>}</div>
      {meshMessage && <div className="mesh-progress" role="status"><LoaderCircle size={13} className="spin" />{meshMessage}</div>}{meshError && <div className="notice error compact" role="alert"><AlertTriangle size={15} />{meshError}</div>}
      {model && <p className="model-details">当前表面：{model.threshold_hu} HU · {model.smoothing ? '已平滑，仅供显示' : '未平滑'} · {model.roi ? `ROI ${model.roi.join(', ')}` : '全体积'} · STL 坐标单位 mm。改变阈值后需重新生成表面。</p>}
      {model && !modelMatches && <p className="mesh-progress"><AlertTriangle size={13} /> 参数已改变，仍显示上次生成的表面。请重新生成后导出。</p>}
    </section>
    <p className="data-note"><span /> 切片直接显示原始 HU。体绘制与表面是派生显示；平滑、阈值和扫描分辨率都会影响外观，不作为测量或诊断依据。</p>
  </div>;
}
