'use client';

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { api, API_BASE } from '@/lib/api';
import type { AssetRecord } from '@/lib/asset-types';
import type { Appearance, PbrMaterial } from '@/lib/pbr-material-types';

export type GarmentMesh = { vertices: number[][]; faces: number[][]; uv: number[][][] };
const meshCache = new Map<string, Promise<GarmentMesh>>();
function loadMesh(record: AssetRecord) {
  const key = `${record.asset_id}:${record.version}`;
  if (!meshCache.has(key)) meshCache.set(key, api<GarmentMesh>(`/assets/${encodeURIComponent(record.asset_id)}/garment-mesh?version=${record.version}`).catch(error => { meshCache.delete(key); throw error; }));
  return meshCache.get(key)!;
}

export function ClothGarmentPreview({ record, appearance, material, thumbnail = false, previewMesh }: {
  record: AssetRecord; appearance: Appearance; material?: PbrMaterial; thumbnail?: boolean; previewMesh?: GarmentMesh;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [mesh, setMesh] = useState<GarmentMesh>();
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [picture, setPicture] = useState('');
  useEffect(() => {
    if (previewMesh) { setMesh(previewMesh); setError(''); setLoaded(false); return; }
    let cancelled = false; setMesh(undefined); setError(''); setLoaded(false); setPicture('');
    void loadMesh(record).then(data => { if (!cancelled) setMesh(data); }).catch(e => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, [record.asset_id, record.version, previewMesh]);
  useEffect(() => {
    if (!mesh || !host.current) return;
    const container = host.current;
    setLoaded(false); setPicture(''); setError('');
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: thumbnail }); }
    catch { setError('浏览器无法启动 WebGL 衣物预览。'); return; }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1; container.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.background = new THREE.Color('#e9ecef');
    const positions = mesh.faces.flatMap(face => face.flatMap(index => { const p = mesh.vertices[index]; return [p[0], p[2], -p[1]]; }));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('uv', new THREE.Float32BufferAttribute(mesh.uv.flat(2), 2));
    geometry.computeVertexNormals(); geometry.computeBoundingBox();
    const center = geometry.boundingBox!.getCenter(new THREE.Vector3()); geometry.translate(-center.x, -center.y, -center.z);
    const extent = geometry.boundingBox!.getSize(new THREE.Vector3()); const size = Math.max(extent.x, extent.y, extent.z);
    const surface = new THREE.MeshStandardMaterial({ side: THREE.DoubleSide, metalness: 0,
      color: material ? appearance.color_mode === 'tint' ? appearance.color : '#ffffff' : appearance.color,
      roughness: material ? appearance.roughness_multiplier ?? 1 : appearance.roughness });
    surface.normalScale.setScalar(appearance.normal_strength ?? 1);
    scene.add(new THREE.Mesh(geometry, surface));
    scene.add(new THREE.HemisphereLight(0xffffff, 0x7a8490, 2));
    for (const [x, y, z, strength] of [[-2, 3, 4, 3], [3, 1, -3, 2]]) {
      const light = new THREE.DirectionalLight(0xffffff, strength); light.position.set(x, y, z); scene.add(light);
    }
    const camera = new THREE.PerspectiveCamera(36, 1, size / 100, size * 20);
    camera.position.set(size * .18, size * .12, size * 1.8);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.enabled = !thumbnail;
    let disposed = false; const textures: THREE.Texture[] = [];
    const resize = () => { renderer.setSize(Math.max(container.clientWidth, 1), thumbnail ? 100 : 300); camera.aspect = Math.max(container.clientWidth, 1) / (thumbnail ? 100 : 300); camera.updateProjectionMatrix(); };
    const observer = new ResizeObserver(resize); observer.observe(container); resize();
    const cleanup = () => {
      if (disposed) return; disposed = true; observer.disconnect(); renderer.setAnimationLoop(null); controls.dispose();
      textures.forEach(t => t.dispose()); geometry.dispose(); surface.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
    const finish = () => {
      if (disposed) return;
      renderer.render(scene, camera); setLoaded(true);
      if (thumbnail) { setPicture(renderer.domElement.toDataURL('image/png')); cleanup(); }
    };
    const loader = new THREE.TextureLoader();
    const maps = material ? (['base_color', 'normal', 'roughness'] as const).map(role => ({ role, url: API_BASE + material.maps[role].url }))
      : appearance.texture !== 'none' ? [{ role: 'base_color' as const, url: API_BASE + '/assets/garment-textures/' + appearance.texture }] : [];
    let remaining = maps.length;
    if (!remaining) finish();
    for (const { role, url } of maps) loader.load(url, texture => {
      if (disposed) { texture.dispose(); return; }
      textures.push(texture); texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
      texture.repeat.setScalar(appearance.uv_scale ?? 1); texture.colorSpace = role === 'base_color' ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      if (role === 'base_color') surface.map = texture; else if (role === 'normal') surface.normalMap = texture; else surface.roughnessMap = texture;
      surface.needsUpdate = true; if (--remaining === 0) finish();
    }, undefined, () => { if (!disposed) setError('衣物贴图加载失败，请检查材质文件。'); });
    if (!thumbnail) renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
    return cleanup;
  }, [mesh, thumbnail, material, appearance.color, appearance.color_mode, appearance.roughness, appearance.roughness_multiplier, appearance.normal_strength, appearance.uv_scale, appearance.texture]);
  return <div data-garment-preview={record.asset_id} data-preview-loaded={loaded} data-preview-material={material?.asset_id ?? appearance.texture}>
    <div ref={host} className={(picture ? 'hidden ' : '') + 'overflow-hidden rounded bg-slate-100'} style={{ height: thumbnail ? 100 : 300 }} aria-label={record.name + '三维预览'} />
    {picture && <img className="h-25 w-full rounded object-contain" src={picture} alt={record.name + '材质缩略图'} />}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {!loaded && !error && <p className="text-xs text-muted-foreground">加载衣物预览…</p>}
    {!thumbnail && <p className="mt-1 text-xs text-muted-foreground">拖动旋转 · 滚轮缩放 · 初始衣物形状；工位录制使用 Isaac 渲染。</p>}
  </div>;
}
