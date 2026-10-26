import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CircleHelp, Download, Minus, Move, Plus, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { FullscreenButton } from './FullscreenButton';
import { useHelp } from './HelpContext';
import { assetUrl, clamp, localText } from './types';
import type { XrayMetadata } from './types';
import './patient-viewer.css';

export function XrayViewer({ studyId, image }: { studyId: string; image: XrayMetadata }) {
  const { openHelp } = useHelp();
  const [zoom, setZoom] = useState(1);
  const [contrast, setContrast] = useState(1);
  const [brightness, setBrightness] = useState(1);
  const [offset, setOffset] = useState([0, 0]);
  const [error, setError] = useState('');
  const host = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  const drag = useRef({ x: 0, y: 0, dx: 0, dy: 0 });
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => { event.preventDefault(); setZoom(value => clamp(value * (event.deltaY < 0 ? 1.1 : 1 / 1.1), 0.25, 8)); };
    element.addEventListener('wheel', wheel, { passive: false });
    return () => element.removeEventListener('wheel', wheel);
  }, []);
  function reset() { setZoom(1); setContrast(1); setBrightness(1); setOffset([0, 0]); }
  return <div className="xray-workspace">
    <div className="viewer-introduction"><div><strong>先看整体，再放大感兴趣的位置</strong><p>滚动鼠标滚轮放大，按住画面拖动。需要对照其他拍摄方向时，在左侧选择另一张片子。</p></div><button className="viewer-help-button" onClick={() => openHelp('xray')}><CircleHelp size={16} /> X 光怎么看？</button></div>
    <div className="ct-toolbar xray-toolbar"><div className="zoom-controls"><button className="icon-button" aria-label="缩小影像" title="缩小影像" onClick={() => setZoom(value => clamp(value / 1.2, 0.25, 8))}><Minus size={16} /></button><span>{Math.round(zoom * 100)}%</span><button className="icon-button" aria-label="放大影像" title="放大影像" onClick={() => setZoom(value => clamp(value * 1.2, 0.25, 8))}><Plus size={16} /></button></div><button className="button subtle" onClick={reset}><RotateCcw size={15} /> 恢复初始显示</button><span className="viewer-toolbar-note">先用完整画面确认位置，再放大看细节</span></div>
    {image.warning && <div className="notice warning compact"><AlertTriangle size={16} />{localText(image.warning)}</div>}
    <section className="view-panel xray-panel" ref={panel}><div className="panel-heading"><div><span className="plane-dot three-dot" /><strong>平面影像</strong><span className="panel-code">当前这一张</span></div><FullscreenButton target={panel} label="二维影像" /></div><div className="xray-host" ref={host} onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, dx: offset[0], dy: offset[1] }; }} onPointerMove={event => { if (event.buttons === 1) setOffset([drag.current.dx + event.clientX - drag.current.x, drag.current.dy + event.clientY - drag.current.y]); }}>
      <img src={assetUrl(studyId, image.file)} alt="本地导入的二维医学影像" draggable={false} style={{ transform: `translate(${offset[0]}px, ${offset[1]}px) scale(${zoom})`, filter: `contrast(${contrast}) brightness(${brightness})` }} onError={() => setError('无法载入这张影像。请重新打开这次检查。')} />{error && <div className="view-message" role="alert">{error}</div>}<span className="render-badge">本机显示副本</span>
    </div><div className="three-footer"><span><Move size={12} /> 拖动平移 · 滚轮缩放</span><span>100% 为适应窗口</span></div></section>
    <details className="viewer-advanced xray-display-details"><summary><SlidersHorizontal size={16} /><span>更多显示调整与导出</span><small>亮度、对比度、保存图片</small></summary><div className="viewer-advanced-content"><p className="advanced-explanation">看不清时可以试着调节明暗。这只改变屏幕上的显示，不能让影像增加新的细节；随时可点“恢复初始显示”。</p><div className="xray-display-controls"><label>对比度 <input type="range" aria-label="X 光对比度" min={0.2} max={3.5} step={0.05} value={contrast} onChange={event => setContrast(Number(event.target.value))} /></label><label>亮度 <input type="range" aria-label="X 光亮度" min={0.2} max={2.5} step={0.05} value={brightness} onChange={event => setBrightness(Number(event.target.value))} /></label><a className="button subtle download-nrrd" href={assetUrl(studyId, image.file)} download><Download size={15} /> 保存显示图片 PNG</a></div><p className="advanced-explanation">图片大小：{image.width} × {image.height} 像素。下载的是导入时生成的显示图片，不包含此处临时调整的亮度、对比度和缩放，也不是原始 DICOM 数据。</p></div></details>
    <p className="data-note"><span /> 一张 X 光里，不同深度的结构会重叠；拍摄方向也会改变外观。普通图片不能直接量出可靠的毫米距离，单张片子也不能说明全部病情。分享前请检查画面中的姓名等信息。</p>
  </div>;
}
