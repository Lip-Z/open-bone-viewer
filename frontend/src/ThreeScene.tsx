import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VolumeRenderShader1 } from 'three/addons/shaders/VolumeShader.js';
import { assetUrl, clamp, loadGzip } from './types';
import type { CtMetadata, SurfaceModel } from './types';

type Runtime = { scene: THREE.Scene; camera: THREE.PerspectiveCamera; renderer: THREE.WebGLRenderer; controls: OrbitControls; object?: THREE.Mesh; shader?: THREE.ShaderMaterial; texture?: THREE.Data3DTexture; colorMap?: THREE.DataTexture; bounds?: THREE.Box3; frame?: number };

function frameObject(rt: Runtime) {
  if (!rt.object) return;
  const bounds = rt.bounds || new THREE.Box3().setFromObject(rt.object);
  const center = bounds.getCenter(new THREE.Vector3());
  const radius = Math.max(bounds.getBoundingSphere(new THREE.Sphere()).radius, 1);
  rt.controls.target.copy(center);
  rt.camera.position.copy(center).add(new THREE.Vector3(radius * 2.5, -radius * 2, radius * 1.1));
  rt.camera.near = Math.max(0.01, radius / 1000); rt.camera.far = radius * 20;
  rt.camera.updateProjectionMatrix();
  rt.controls.minDistance = radius * 0.05; rt.controls.maxDistance = radius * 12;
  rt.controls.update();
}

export function ThreeScene({ studyId, meta, mode, threshold, model, resetKey }: { studyId: string; meta: CtMetadata; mode: 'volume' | 'surface'; threshold: number; model?: SurfaceModel; resetKey: number }) {
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<Runtime | null>(null);
  const thresholdRef = useRef(threshold);
  const [message, setMessage] = useState('正在载入三维数据…');
  useEffect(() => { thresholdRef.current = threshold; }, [threshold]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    setMessage('正在载入三维数据…');
    const abort = new AbortController();
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); }
    catch { setMessage('无法启动 WebGL 三维显示。请在新版 Chrome 或 Edge 中开启硬件加速。切片仍可查看。'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    renderer.setClearColor(0x080e13); renderer.outputColorSpace = THREE.SRGBColorSpace;
    const canvas = renderer.domElement;
    canvas.tabIndex = 0; canvas.style.touchAction = 'none';
    canvas.setAttribute('aria-label', '三维影像，拖动旋转、右键平移、滚轮缩放');
    element.appendChild(canvas);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 5000); camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = true; controls.dampingFactor = 0.07; controls.rotateSpeed = 1.1; controls.screenSpacePanning = true;
    const rt: Runtime = { scene, camera, renderer, controls }; runtime.current = rt;
    scene.add(new THREE.HemisphereLight(0xe5f4ff, 0x28333b, 2));
    const key = new THREE.DirectionalLight(0xffead4, 3.2); key.position.set(1, -1, 2); scene.add(key);
    const rim = new THREE.DirectionalLight(0x9cd9ed, 1.5); rim.position.set(-1, 1, 0.5); scene.add(rim);
    const resize = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width < 2 || height < 2) return;
      renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
    }); resize.observe(element);
    const draw = () => { rt.frame = requestAnimationFrame(draw); controls.update(); renderer.render(scene, camera); }; draw();

    async function load() {
      if (mode === 'volume') {
        const data = meta.volume_rendering;
        if (!data) throw new Error('这次检查没有体绘制数据。');
        const buffer = await loadGzip(assetUrl(studyId, data.file), abort.signal);
        if (abort.signal.aborted) return;
        const [nx, ny, nz] = data.dimensions_xyz;
        if (buffer.byteLength !== nx * ny * nz) throw new Error('体绘制数据尺寸不完整。');
        const gl = renderer.getContext() as WebGL2RenderingContext;
        const maximum = gl.getParameter(gl.MAX_3D_TEXTURE_SIZE) as number;
        if (Math.max(nx, ny, nz) > maximum) throw new Error('体数据超过当前显卡支持的三维纹理大小。切片仍可查看。');
        const texture = new THREE.Data3DTexture(new Uint8Array(buffer), nx, ny, nz);
        texture.format = THREE.RedFormat; texture.type = THREE.UnsignedByteType;
        texture.minFilter = THREE.LinearFilter; texture.magFilter = THREE.LinearFilter;
        texture.unpackAlignment = 1; texture.needsUpdate = true; rt.texture = texture;
        const colors = new Uint8Array(256 * 4);
        for (let i = 0; i < 256; i++) { colors[i * 4] = 205 + Math.round(i / 255 * 43); colors[i * 4 + 1] = 202 + Math.round(i / 255 * 43); colors[i * 4 + 2] = 189 + Math.round(i / 255 * 44); colors[i * 4 + 3] = 255; }
        const colorMap = new THREE.DataTexture(colors, 256, 1, THREE.RGBAFormat); colorMap.needsUpdate = true; rt.colorMap = colorMap;
        const uniforms = THREE.UniformsUtils.clone(VolumeRenderShader1.uniforms);
        uniforms.u_data.value = texture; uniforms.u_size.value.set(nx, ny, nz); uniforms.u_clim.value.set(0, 1);
        uniforms.u_renderstyle.value = 1; uniforms.u_renderthreshold.value = clamp((thresholdRef.current - data.min_hu) / (data.max_hu - data.min_hu || 1), 0, 1); uniforms.u_cmdata.value = colorMap;
        const material = new THREE.ShaderMaterial({ uniforms, vertexShader: VolumeRenderShader1.vertexShader, fragmentShader: VolumeRenderShader1.fragmentShader, side: THREE.BackSide }); rt.shader = material;
        const geometry = new THREE.BoxGeometry(nx, ny, nz); geometry.translate(nx / 2 - 0.5, ny / 2 - 0.5, nz / 2 - 0.5);
        const object = new THREE.Mesh(geometry, material);
        const [sx, sy, sz] = data.spacing_xyz_mm;
        object.scale.set(-sx, -sy, sz); object.position.set(-meta.origin_lps_mm[0], -meta.origin_lps_mm[1], meta.origin_lps_mm[2]); object.updateMatrixWorld(true);
        const bounds = data.content_bounds_xyz || [[0, 0, 0], [nx - 1, ny - 1, nz - 1]];
        const contentBox = new THREE.Box3();
        for (const x of [bounds[0][0], bounds[1][0]]) for (const y of [bounds[0][1], bounds[1][1]]) for (const z of [bounds[0][2], bounds[1][2]]) contentBox.expandByPoint(object.localToWorld(new THREE.Vector3(x, y, z)));
        rt.object = object; rt.bounds = contentBox; scene.add(object);
      } else {
        if (!model) throw new Error('请先生成阈值表面。');
        const buffer = await loadGzip(assetUrl(studyId, model.mesh_file), abort.signal);
        if (abort.signal.aborted) return;
        if (buffer.byteLength < 12) throw new Error('表面模型数据不完整。');
        const view = new DataView(buffer);
        if (view.getUint32(0, true) !== 0x314d5443) throw new Error('表面模型格式错误。');
        const vertices = view.getUint32(4, true); const faces = view.getUint32(8, true);
        if (!vertices || !faces || buffer.byteLength !== 12 + vertices * 12 + faces * 12) throw new Error('表面模型尺寸不完整。');
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(buffer, 12, vertices * 3), 3));
        geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(buffer, 12 + vertices * 12, faces * 3), 1));
        geometry.computeVertexNormals(); geometry.computeBoundingBox();
        const material = new THREE.MeshStandardMaterial({ color: 0xe8deca, roughness: 0.62, metalness: 0.01, side: THREE.DoubleSide });
        const object = new THREE.Mesh(geometry, material); rt.object = object; scene.add(object);
      }
      frameObject(rt); setMessage('');
    }
    void load().catch(cause => { if (!abort.signal.aborted) setMessage(cause instanceof Error ? cause.message : '三维显示失败'); });
    return () => {
      abort.abort(); resize.disconnect(); if (rt.frame) cancelAnimationFrame(rt.frame); controls.dispose();
      if (rt.object) { rt.object.geometry.dispose(); const material = rt.object.material; if (Array.isArray(material)) material.forEach(item => item.dispose()); else material.dispose(); }
      rt.texture?.dispose(); rt.colorMap?.dispose(); renderer.dispose(); canvas.remove(); runtime.current = null;
    };
  }, [studyId, meta.volume_rendering, meta.origin_lps_mm, mode, model]);

  useEffect(() => {
    const rt = runtime.current; const data = meta.volume_rendering;
    if (rt?.shader && data) rt.shader.uniforms.u_renderthreshold.value = clamp((threshold - data.min_hu) / (data.max_hu - data.min_hu || 1), 0, 1);
  }, [threshold, meta.volume_rendering]);
  useEffect(() => { if (runtime.current) frameObject(runtime.current); }, [resetKey]);

  return <div ref={host} className="three-host">{message && <div className="view-message" role="status">{message}</div>}<div className="render-badge">{mode === 'volume' ? '派生体数据 · 显示插值' : '阈值网格 · RAS / mm'}</div></div>;
}
