import {
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  SphereGeometry,
} from "three";

/**
 * Procedural head + brain fallback (PLAN.md "procedural fallback").
 *
 * The real Unity assets (Realistic_White_Female_Head.obj, Realistic_Brain.fbx)
 * can be dropped in later as brain.glb / head.glb and loaded with GLTFLoader;
 * until then this gives the scene its shape: a translucent head ellipsoid with
 * an adjustable vertical cutaway (mirroring HumanHead.shader's _Cutoff) and a
 * brain-like inner mesh.
 */
export class BrainHead {
  readonly group = new Group();
  readonly head: Mesh;
  readonly brain: Mesh;
  private headMaterial: MeshPhysicalMaterial;
  private cutoff = 1.2; // world Y above which the head fades out

  constructor() {
    // Head: slightly egg-shaped, translucent.
    const headGeo = new SphereGeometry(1.0, 64, 48);
    headGeo.scale(0.92, 1.12, 1.05);
    this.headMaterial = new MeshPhysicalMaterial({
      color: 0xd9c6b8,
      roughness: 0.85,
      metalness: 0.0,
      transparent: true,
      opacity: 0.28,
      transmission: 0.2,
      side: 2, // DoubleSide
      clipShadows: true,
    });
    this.head = new Mesh(headGeo, this.headMaterial);

    // Brain: lumpy inner mesh.
    const brainGeo = new IcosahedronGeometry(0.62, 4);
    this._displace(brainGeo);
    const brainMat = new MeshStandardMaterial({
      color: 0xc98b9a,
      roughness: 0.6,
      metalness: 0.05,
      emissive: 0x3a1f28,
      emissiveIntensity: 0.4,
    });
    this.brain = new Mesh(brainGeo, brainMat);
    this.brain.position.y = -0.05;

    this.group.add(this.head, this.brain);
  }

  private _displace(geo: IcosahedronGeometry): void {
    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const y = pos.getY(i);
      const z = pos.getZ(i);
      const n =
        Math.sin(x * 9) * Math.cos(y * 8) * Math.sin(z * 10) * 0.04 +
        Math.sin(x * 18 + z * 5) * 0.02;
      const len = Math.hypot(x, y, z) || 1;
      pos.setXYZ(i, x + (x / len) * n, y + (y / len) * n, z + (z / len) * n);
    }
    geo.computeVertexNormals();
  }

  /** Head transparency 0..1 (preset control). */
  setHeadOpacity(opacity: number): void {
    this.headMaterial.opacity = Math.min(1, Math.max(0, opacity));
    this.headMaterial.visible = this.headMaterial.opacity > 0.01;
  }

  setHeadVisible(visible: boolean): void {
    this.head.visible = visible;
  }

  setBrainVisible(visible: boolean): void {
    this.brain.visible = visible;
  }

  /** Adjust the vertical cutaway (arrow keys), echoing Unity's _Cutoff. */
  adjustCutoff(delta: number): void {
    this.cutoff = Math.max(-0.5, Math.min(1.3, this.cutoff + delta));
    // Approximate the cutaway by clipping head geometry above the plane.
    this.headMaterial.clippingPlanes = null;
    // Simple visual proxy: lower opacity as the cutaway descends.
    const t = (this.cutoff + 0.5) / 1.8;
    this.setHeadOpacity(0.05 + 0.3 * t);
  }
}
