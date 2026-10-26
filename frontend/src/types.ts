export type XYZ = [number, number, number];
export type Study = {
  id: string; kind: 'ct' | 'xray'; label: string; modality: string;
  count: number; rows: number; columns: number; supported: boolean;
  reason?: string; ready: boolean;
};
export type SurfaceModel = {
  threshold_hu: number; vertices: number; triangles: number;
  mesh_file: string; stl_file: string; smoothing?: boolean; roi?: number[] | null;
};
export type VolumeRendering = {
  file: string; dimensions_xyz: XYZ; spacing_xyz_mm: XYZ;
  content_bounds_xyz: [XYZ, XYZ]; min_hu: number; max_hu: number; source?: string;
};
export type CtMetadata = {
  dimensions_xyz: XYZ; spacing_xyz_mm: XYZ; origin_lps_mm: XYZ;
  source_dimensions_xyz?: XYZ; source_spacing_xyz_mm?: XYZ;
  dtype: 'float32'; warnings?: string[]; models: SurfaceModel[];
  volume_rendering?: VolumeRendering;
  body_volume_rendering?: VolumeRendering;
};
export type XrayMetadata = { file: string; width: number; height: number; warning?: string };
export type Job = { id: string; status: 'queued' | 'running' | 'done' | 'error'; message: string; result?: { study_id: string; metadata?: CtMetadata; image?: XrayMetadata; model?: SurfaceModel } };
export const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
export const assetUrl = (studyId: string, file: string) => `/api/studies/${encodeURIComponent(studyId)}/assets/${encodeURIComponent(file)}`;
export const voxelValue = (v: Float32Array, d: XYZ, p: XYZ) => v[(p[2] * d[1] + p[1]) * d[0] + p[0]];

const translatedMessages: Record<string, string> = {
  'CT localizer images cannot form a 3D volume.': '这是定位像，不能组成三维 CT。请选择有连续切片的 CT 序列。',
  'Oblique CT orientations are not supported in this version; use an axis-aligned reconstruction.': '首版暂不支持斜切 CT，请选择沿解剖轴重建的常规序列。',
  'Gantry-tilted CT is not supported in this version.': '首版暂不支持机架倾斜扫描，请选择无倾斜的重建序列。',
  'Tilted or shifted CT slices are not supported in this version.': '此序列的切片存在倾斜或位置偏移，首版暂不能正确重建。',
  'Irregular CT slice spacing is not supported in this version.': '此序列的层间距不规则，首版暂不支持。请选择层间距均匀的重建序列。',
  'Multi-frame CT is not supported in this version.': '首版暂不支持多帧 CT，请选择常规单帧切片序列。',
  'Multi-frame DICOM images are not supported in this version.': '首版暂不支持多帧 DICOM 影像。',
  'Only conventional single-frame CT images are supported in this version.': '首版仅支持常规单帧 CT，暂不支持此类 CT 对象。',
  'A CT volume needs at least two spatially distinct slices.': '三维 CT 至少需要两张空间位置不同的切片，请导入完整序列。',
  'CT contains duplicate or overlapping slice positions.': '此序列包含重复或重叠层面，无法确定唯一的 CT 体积。',
  'This CT is too large for this version. Import a smaller series or reconstruction.': '这组 CT 超出首版的内存限制，请选择范围较小的重建序列。',
  'This DICOM imaging modality is not supported in this version.': '首版暂不支持这种 DICOM 检查类型。',
  'DICOM pixels could not be decoded. The file may be damaged or need a compression decoder (pylibjpeg or GDCM).': '无法解码此 DICOM。文件可能损坏，或使用了当前尚未支持的压缩编码。',
  'This threshold has no surface in the selected volume. Choose another HU threshold or ROI.': '当前阈值在选区内没有形成表面，请调整阈值或扩大生成范围。',
  '3D rendering is a smoothed, quantized display copy; use the original MPR or source NRRD for voxel values.': '三维体绘制使用经过平滑和量化的显示副本。需要查看原始 HU 值时，请使用联动切片或下载原始 NRRD。',
  'Threshold surfaces are not anatomical segmentation and may include other bones, casts or scanner supports.': '阈值表面不等于解剖分割，可能同时包含其他骨骼、石膏或扫描床等结构。',
  'Largest connected tissue preview may hide separate body parts; original MPR unchanged.': '主体预览只显示最大的连通组织，可能隐藏分离部位，仅影响三维体绘制。原始切片、NRRD 和阈值表面不受影响；可切换“全部结构”对照。',
  'Images may contain burned-in personal information. Local display does not automatically remove it.': '影像像素中可能带有姓名等身份文字，本地显示不会自动去除这些内容。',
  'Waiting for image processing.': '已进入本地处理队列…',
  'Processing locally on this computer.': '正在本机处理影像…',
  'Processing complete.': '本地处理完成，正在载入…',
};
export const localText = (message: string) => translatedMessages[message] || message;
export function studyLabel(study: Study): string {
  return study.label
    .replace(/^CT series (\d+)$/, 'CT 序列 $1')
    .replace(/^DICOM projection (\d+)$/, 'DICOM 投照影像 $1')
    .replace(/^DICOM image (\d+)$/, 'DICOM 图片 $1')
    .replace(/^Image (\d+)$/, '普通图片 $1') || (study.kind === 'ct' ? 'CT 检查' : '二维影像');
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try { const data = await response.json(); if (typeof data.detail === 'string') message = data.detail; else if (typeof data.message === 'string') message = data.message; } catch { /* Keep the status when the response is not JSON. */ }
    throw new Error(localText(message));
  }
  return response.json() as Promise<T>;
}
export async function loadGzip(url: string, signal?: AbortSignal): Promise<ArrayBuffer> {
  const response = await fetch(url, { signal });
  if (!response.ok || !response.body) throw new Error(`无法读取影像数据（${response.status}）`);
  if (!('DecompressionStream' in window)) throw new Error('浏览器不支持解压影像，请使用新版 Chrome、Edge 或 Firefox。');
  return new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
}
export async function waitForJob(id: string, signal: AbortSignal, onProgress: (job: Job) => void): Promise<Job> {
  while (!signal.aborted) {
    const job = await api<Job>(`/jobs/${encodeURIComponent(id)}`, { signal });
    onProgress(job);
    if (job.status === 'error') throw new Error(localText(job.message) || '处理失败');
    if (job.status === 'done') return job;
    await new Promise<void>((resolve, reject) => {
      const done = () => { signal.removeEventListener('abort', cancel); resolve(); };
      const timer = window.setTimeout(done, 650);
      const cancel = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
      signal.addEventListener('abort', cancel, { once: true });
    });
  }
  throw new DOMException('Aborted', 'AbortError');
}
