import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Download, Minus, Move, Plus, RotateCcw } from 'lucide-react';
import { FullscreenButton } from './FullscreenButton';
import { assetUrl, clamp, localText } from './types';
import type { XrayMetadata } from './types';

export function XrayViewer({ studyId, image }: { studyId: string; image: XrayMetadata }) {
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
    <div className="ct-toolbar xray-toolbar"><div className="zoom-controls"><button className="icon-button" aria-label="缩小影像" onClick={() => setZoom(value => clamp(value / 1.2, 0.25, 8))}><Minus size={16} /></button><span>{Math.round(zoom * 100)}%</span><button className="icon-button" aria-label="放大影像" onClick={() => setZoom(value => clamp(value * 1.2, 0.25, 8))}><Plus size={16} /></button></div><label>对比度 <input type="range" aria-label="X 光对比度" min={0.2} max={3.5} step={0.05} value={contrast} onChange={event => setContrast(Number(event.target.value))} /></label><label>亮度 <input type="range" aria-label="X 光亮度" min={0.2} max={2.5} step={0.05} value={brightness} onChange={event => setBrightness(Number(event.target.value))} /></label><button className="button subtle" onClick={reset}><RotateCcw size={15} /> 重置</button><a className="button subtle download-nrrd" href={assetUrl(studyId, image.file)} download><Download size={15} /> 显示图 PNG</a></div>
    {image.warning && <div className="notice warning compact"><AlertTriangle size={16} />{localText(image.warning)}</div>}
    <section className="view-panel xray-panel" ref={panel}><div className="panel-heading"><div><span className="plane-dot three-dot" /><strong>二维影像</strong><span className="panel-code">{image.width} × {image.height}</span></div><FullscreenButton target={panel} label="二维影像" /></div><div className="xray-host" ref={host} onPointerDown={event => { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, dx: offset[0], dy: offset[1] }; }} onPointerMove={event => { if (event.buttons === 1) setOffset([drag.current.dx + event.clientX - drag.current.x, drag.current.dy + event.clientY - drag.current.y]); }}>
      <img src={assetUrl(studyId, image.file)} alt="本地导入的二维医学影像" draggable={false} style={{ transform: `translate(${offset[0]}px, ${offset[1]}px) scale(${zoom})`, filter: `contrast(${contrast}) brightness(${brightness})` }} onError={() => setError('无法载入二维影像。请重新打开这次检查。')} />{error && <div className="view-message" role="alert">{error}</div>}<span className="render-badge">显示图 · 非原始 DICOM 像素</span>
    </div><div className="three-footer"><span><Move size={12} /> 拖动平移 · 滚轮缩放</span><span>100% 为适应窗口</span></div></section>
    <p className="data-note"><span /> 亮度和对比度仅改变显示。普通图片没有可靠的毫米标定；DICOM 或图片中的烧录身份文字不会自动去除。</p>
  </div>;
}
