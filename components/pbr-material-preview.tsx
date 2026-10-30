'use client';
import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { API_BASE } from '@/lib/api';
import type { Appearance, PbrMaterial } from '@/lib/pbr-material-types';

export function PbrMaterialPreview({ material, appearance, surface: isSurface = false }: { material: PbrMaterial; appearance: Appearance; surface?: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(0);
  useEffect(() => {
    const host = container.current;
    if (!host) return;
    setError(''); setLoaded(0);
    let disposed = false;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setError('无法启动 WebGL 三维预览，请在支持 WebGL 的浏览器中打开。'); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    host.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.background = new THREE.Color('#343a40');
    const camera = new THREE.PerspectiveCamera(40, 1, .01, 20); camera.position.set(1.3, 1.5, 2);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x606068, 2));
    for (const [x, y, z, intensity] of [[-2, 3, 3, 5], [3, 1, -2, 3]]) {
      const light = new THREE.DirectionalLight(0xffffff, intensity); light.position.set(x, y, z); scene.add(light);
    }
    const geometry = new THREE.PlaneGeometry(1.6, 1.6, 96, 96);
    const points = geometry.attributes.position;
    for (let i = 0; i < points.count; i++) {
      const x = points.getX(i), y = points.getY(i);
      points.setZ(i, isSurface ? 0 : .1 * Math.sin(x * 7) * Math.cos(y * 3));
    }
    geometry.computeVertexNormals();
    const surface = new THREE.MeshStandardMaterial({ side: THREE.DoubleSide, metalness: 0,
      color: appearance.color_mode === 'tint' ? appearance.color : '#ffffff', roughness: appearance.roughness_multiplier ?? 1 });
    surface.normalScale.setScalar(appearance.normal_strength ?? 1);
    const cloth = new THREE.Mesh(geometry, surface); cloth.rotation.x = -Math.PI / 3; scene.add(cloth);
    const loader = new THREE.TextureLoader(); const textures: THREE.Texture[] = [];
    for (const role of ['base_color', 'normal', 'roughness'] as const) {
      loader.load(API_BASE + material.maps[role].url, texture => {
        if (disposed) { texture.dispose(); return; }
        textures.push(texture); texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.repeat.setScalar((appearance.uv_scale ?? 1) * (isSurface ? 1.6 : 1));
        texture.colorSpace = role === 'base_color' ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        if (role === 'base_color') surface.map = texture;
        else if (role === 'normal') surface.normalMap = texture;
        else surface.roughnessMap = texture;
        surface.needsUpdate = true;
        setLoaded(current => current + 1);
      }, undefined, () => { if (!disposed) setError('贴图加载失败，请检查材质文件和 API 连接。'); });
    }
    const resize = () => {
      const width = Math.max(host.clientWidth, 1), height = 320;
      renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize); observer.observe(host); resize();
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
    return () => {
      disposed = true; observer.disconnect(); renderer.setAnimationLoop(null); controls.dispose();
      textures.forEach(texture => texture.dispose()); geometry.dispose(); surface.dispose(); renderer.dispose();
      renderer.domElement.remove();
    };
  }, [material, appearance.color, appearance.color_mode, appearance.roughness_multiplier, appearance.normal_strength, appearance.uv_scale, isSurface]);
  return <div><div ref={container} data-material-id={material.asset_id} data-pbr-loaded={loaded} className="min-h-80 overflow-hidden rounded border" aria-label={isSurface ? 'PBR 三维表面预览' : 'PBR 三维织物预览'} />{error && <p role="alert" className="text-destructive">{error}</p>}{!error && loaded < 3 && <p className="text-xs">加载贴图 {loaded}/3…</p>}<p className="mt-2 text-xs text-muted-foreground">拖动旋转，滚轮缩放 · BaseColor / Normal / Roughness · 工位录制以 Isaac 渲染为准</p></div>;
}
