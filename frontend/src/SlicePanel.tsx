import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { FullscreenButton } from './FullscreenButton';
import { clamp, voxelValue } from './types';
import type { CtMetadata, XYZ } from './types';

export const planes = [
  { axis: 2, name: '横断位', label: '横着看', code: 'AXIAL', color: '#e57c86', vertical: ['A', 'P'], horizontal: ['R', 'L'] },
  { axis: 1, name: '冠状位', label: '正面看', code: 'CORONAL', color: '#75c5b1', vertical: ['S', 'I'], horizontal: ['R', 'L'] },
  { axis: 0, name: '矢状位', label: '侧面看', code: 'SAGITTAL', color: '#d8ba79', vertical: ['S', 'I'], horizontal: ['A', 'P'] },
];
const directions: Record<string, string> = { A: '前', P: '后', S: '上', I: '下', R: '右', L: '左' };

export function SlicePanel({ plane, meta, volume, point, onPoint, center, width }: {
  plane: typeof planes[number]; meta: CtMetadata; volume: Float32Array; point: XYZ;
  onPoint: (point: XYZ) => void; center: number; width: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const transform = useRef({ x: 0, y: 0, w: 1, h: 1 });
  const [box, setBox] = useState([400, 350]);
  const axis = plane.axis;
  const [nx, ny, nz] = meta.dimensions_xyz;
  const [sx, sy, sz] = meta.spacing_xyz_mm;
  const imageWidth = axis === 0 ? ny : nx;
  const imageHeight = axis === 2 ? ny : nz;
  const pixelWidth = axis === 0 ? sy : sx;
  const pixelHeight = axis === 2 ? sy : sz;

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setBox([entry.contentRect.width, entry.contentRect.height]));
    if (hostRef.current) observer.observe(hostRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(box[0] * dpr));
    canvas.height = Math.max(1, Math.round(box[1] * dpr));
    const context = canvas.getContext('2d');
    if (!context || box[0] < 5 || box[1] < 5) return;
    context.scale(dpr, dpr);
    context.fillStyle = '#080e13';
    context.fillRect(0, 0, box[0], box[1]);
    const image = document.createElement('canvas');
    image.width = imageWidth; image.height = imageHeight;
    const imageContext = image.getContext('2d')!;
    const pixels = imageContext.createImageData(imageWidth, imageHeight);
    const low = center - width / 2;
    for (let row = 0; row < imageHeight; row++) {
      for (let col = 0; col < imageWidth; col++) {
        const x = axis === 0 ? point[0] : col;
        const y = axis === 2 ? row : axis === 1 ? point[1] : col;
        const z = axis === 2 ? point[2] : nz - 1 - row;
        const gray = Math.round(clamp((voxelValue(volume, meta.dimensions_xyz, [x, y, z]) - low) / width, 0, 1) * 255);
        const index = (row * imageWidth + col) * 4;
        pixels.data[index] = gray; pixels.data[index + 1] = gray; pixels.data[index + 2] = gray; pixels.data[index + 3] = 255;
      }
    }
    imageContext.putImageData(pixels, 0, 0);
    const scale = Math.max(0.00001, Math.min((box[0] - 35) / (imageWidth * pixelWidth), (box[1] - 35) / (imageHeight * pixelHeight)));
    const w = imageWidth * pixelWidth * scale;
    const h = imageHeight * pixelHeight * scale;
    const x = (box[0] - w) / 2; const y = (box[1] - h) / 2;
    transform.current = { x, y, w, h };
    context.imageSmoothingEnabled = false;
    context.drawImage(image, x, y, w, h);
    const crossX = x + ((axis === 0 ? point[1] : point[0]) + 0.5) / imageWidth * w;
    const crossY = y + ((axis === 2 ? point[1] : nz - 1 - point[2]) + 0.5) / imageHeight * h;
    context.save(); context.beginPath(); context.rect(x, y, w, h); context.clip();
    context.strokeStyle = plane.color; context.globalAlpha = 0.85; context.lineWidth = 0.75;
    context.beginPath(); context.moveTo(crossX, y); context.lineTo(crossX, y + h); context.moveTo(x, crossY); context.lineTo(x + w, crossY); context.stroke();
    context.beginPath(); context.arc(crossX, crossY, 4, 0, Math.PI * 2); context.stroke(); context.restore();
  }, [axis, box, center, imageHeight, imageWidth, meta, nz, pixelHeight, pixelWidth, plane.color, point, volume, width]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const next: XYZ = [...point];
      next[axis] = clamp(point[axis] + (event.deltaY > 0 ? 1 : -1), 0, meta.dimensions_xyz[axis] - 1);
      onPoint(next);
    };
    host.addEventListener('wheel', wheel, { passive: false });
    return () => host.removeEventListener('wheel', wheel);
  }, [point, axis, meta, onPoint]);

  function locate(event: PointerEvent<HTMLCanvasElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const t = transform.current;
    const col = clamp(Math.floor((event.clientX - bounds.left - t.x) / t.w * imageWidth), 0, imageWidth - 1);
    const row = clamp(Math.floor((event.clientY - bounds.top - t.y) / t.h * imageHeight), 0, imageHeight - 1);
    const next: XYZ = [...point];
    if (axis === 0) { next[1] = col; next[2] = nz - 1 - row; }
    if (axis === 1) { next[0] = col; next[2] = nz - 1 - row; }
    if (axis === 2) { next[0] = col; next[1] = row; }
    onPoint(next);
  }

  return <section ref={panelRef} className="view-panel slice-panel" style={{ '--plane-color': plane.color } as React.CSSProperties}>
    <div className="panel-heading"><div><span className="plane-dot" /><strong>{plane.label}</strong><span className="panel-code patient-plane-name">{plane.name}</span></div><FullscreenButton target={panelRef} label={plane.name} /></div>
    <div className="slice-host" ref={hostRef}>
      <canvas ref={canvasRef} aria-label={`${plane.name}切片，点击或拖动联动定位，滚轮切换层面`} tabIndex={0} onKeyDown={event => { if (event.key === 'ArrowUp' || event.key === 'ArrowDown') { event.preventDefault(); const next: XYZ = [...point]; next[axis] = clamp(point[axis] + (event.key === 'ArrowDown' ? 1 : -1), 0, meta.dimensions_xyz[axis] - 1); onPoint(next); } }} onPointerDown={event => { if (event.button === 0) { event.currentTarget.setPointerCapture(event.pointerId); locate(event); } }} onPointerMove={event => { if (event.buttons === 1) locate(event); }} />
      <span className="orientation top" title={`身体的${directions[plane.vertical[0]]}方`}>{directions[plane.vertical[0]]} {plane.vertical[0]}</span><span className="orientation bottom" title={`身体的${directions[plane.vertical[1]]}方`}>{directions[plane.vertical[1]]} {plane.vertical[1]}</span><span className="orientation left" title={`身体的${directions[plane.horizontal[0]]}方`}>{directions[plane.horizontal[0]]} {plane.horizontal[0]}</span><span className="orientation right" title={`身体的${directions[plane.horizontal[1]]}方`}>{directions[plane.horizontal[1]]} {plane.horizontal[1]}</span>
      <span className="slice-info">点一下，对照同一位置</span><span className="source-tag">原始切片</span>
    </div>
    <div className="slice-slider"><span>第 {point[axis] + 1} 层<small> / {meta.dimensions_xyz[axis]}</small></span><input aria-label={`${plane.name}层面`} aria-valuetext={`第 ${point[axis] + 1} 层，共 ${meta.dimensions_xyz[axis]} 层`} type="range" min={0} max={meta.dimensions_xyz[axis] - 1} value={point[axis]} onChange={event => { const next: XYZ = [...point]; next[axis] = Number(event.target.value); onPoint(next); }} /></div>
  </section>;
}
