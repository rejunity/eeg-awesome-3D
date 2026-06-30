import {
  BufferGeometry,
  CanvasTexture,
  Color,
  ConeGeometry,
  Group,
  LinearFilter,
  Matrix3,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PointLight,
  Quaternion,
  Raycaster,
  Sprite,
  SpriteMaterial,
  SphereGeometry,
  Vector3,
} from "three";
import type { ElectrodeMeta } from "../net/protocol";
import { electrodeColor, type ColorScheme } from "./colormap";

const BLACK = new Color(0x000000);
// Dim neutral glow for electrodes not populated by the stream, shown only when
// the "show all electrodes" debug toggle is on (otherwise they stay black).
const INACTIVE_GLOW = new Color(0x2a3340);
// How far above the electrode marker (along the outward normal) the name floats.
const LABEL_OFFSET = 0.12;
// Base label world size (canvas aspect 2:1) and the default scale (GUI default).
const LABEL_W = 0.126;
const LABEL_H = 0.063;
export const DEFAULT_LABEL_SCALE = 1.0;

interface ElectrodeNode {
  name: string;
  mesh: Mesh;
  light: PointLight;
  material: MeshStandardMaterial;
  label: Sprite;
  nominal: Vector3; // nominal position on the ~unit electrode shell
}

export type ElectrodeShape = "sphere" | "cone";

const X_AXIS = new Vector3(1, 0, 0);
const CONE_UP = new Vector3(0, 1, 0); // ConeGeometry apex points +Y
const CONE_HEIGHT = 0.11;
// Cast from this far out (along the electrode direction) toward the head centre
// so the first hit is always the outer scalp, even if the nominal point is
// inside the head bounding volume.
const RAY_START_RADIUS = 10;

/**
 * Electrode markers placed by CGX label. Markers are raycast onto the head
 * surface (toward the brain centre) and placed just outside it along the
 * surface normal — mirroring the Unity Electrode.cs raycast. Each marker is a
 * sphere or an outward-pointing cone with a point light whose colour/intensity
 * is driven by the latest processed value (red→green parity) or band energy.
 *
 * Channel names are matched case/space-insensitively; missing channels are
 * left dark. A debug mode isolates one electrode (the old `debugElectrode`).
 */
export class Electrodes {
  readonly group = new Group(); // added to the scene at the origin (world == local)
  private nodes = new Map<string, ElectrodeNode>();
  private indicatorsVisible = true;
  private debugElectrode: string | null = null;
  private colorScheme: ColorScheme = "blue-yellow";
  private shape: ElectrodeShape = "sphere";
  // Debug: when true, electrodes absent from the stream are shown with a dim
  // neutral glow instead of being left black/invisible.
  private showAll = false;
  // Keys of the nodes populated by the most recent frame's channels.
  private activeKeys = new Set<string>();

  private readonly sphereGeo = new SphereGeometry(0.04, 16, 12);
  private readonly coneGeo = new ConeGeometry(0.045, CONE_HEIGHT, 20);
  private readonly raycaster = new Raycaster();

  constructor(metas: ElectrodeMeta[]) {
    for (const meta of metas) {
      // Black base so the marker shows only its emissive value colour (so a
      // value at the running mean reads as black).
      const material = new MeshStandardMaterial({
        color: 0x000000,
        emissive: 0x000000,
        roughness: 0.4,
      });
      const mesh = new Mesh(this.sphereGeo, material);
      const nominal = new Vector3(...meta.position).multiplyScalar(1.04);
      mesh.position.copy(nominal);

      const light = new PointLight(0x000000, 0.0, 0.8, 2.0);
      light.position.copy(nominal);

      const label = makeLabelSprite(meta.name);
      label.position.copy(nominal).multiplyScalar(1 + LABEL_OFFSET);

      this.group.add(mesh, light, label);
      this.nodes.set(normalize(meta.name), {
        name: meta.name,
        mesh,
        light,
        material,
        label,
        nominal,
      });
    }
  }

  setIndicatorsVisible(v: boolean): void {
    this.indicatorsVisible = v;
    for (const n of this.nodes.values()) n.light.visible = v;
  }

  toggleIndicators(): void {
    this.setIndicatorsVisible(!this.indicatorsVisible);
  }

  setDebugElectrode(name: string | null): void {
    this.debugElectrode = name ? normalize(name) : null;
  }

  /**
   * Debug: show every electrode, including those not populated by the stream.
   * Unpopulated markers get a dim neutral glow so all 10-10 sites are visible;
   * turning it off restores them to black. Applied immediately to the inactive
   * set so it works even when no frames are arriving.
   */
  setShowAll(v: boolean): void {
    this.showAll = v;
    for (const [key, node] of this.nodes) {
      if (!this.activeKeys.has(key)) this.paintInactive(node);
    }
  }

  /** Paint a node not driven by the stream: dim glow if showAll, else black. */
  private paintInactive(node: ElectrodeNode): void {
    const isolated =
      this.debugElectrode !== null && normalize(node.name) !== this.debugElectrode;
    const glow = this.showAll && !isolated ? INACTIVE_GLOW : BLACK;
    node.material.emissive.copy(glow);
    node.material.emissiveIntensity = 1.0;
    node.light.intensity = 0; // unpopulated markers don't cast coloured light
  }

  setColorScheme(scheme: ColorScheme): void {
    this.colorScheme = scheme;
  }

  /** Show/hide the floating electrode-name labels. */
  setLabelsVisible(v: boolean): void {
    for (const n of this.nodes.values()) n.label.visible = v;
  }

  /** Scale the floating electrode-name labels (1 = default size, 2:1 aspect). */
  setLabelScale(scale: number): void {
    const s = Math.max(0.05, scale);
    for (const n of this.nodes.values()) n.label.scale.set(LABEL_W * s, LABEL_H * s, 1);
  }

  setShape(shape: ElectrodeShape): void {
    this.shape = shape;
    const geo: BufferGeometry = shape === "cone" ? this.coneGeo : this.sphereGeo;
    for (const n of this.nodes.values()) {
      n.mesh.geometry = geo;
      if (shape === "sphere") n.mesh.quaternion.identity();
    }
  }

  /**
   * Raycast every electrode onto the head surface and place it just outside the
   * hit along the surface normal. ``pitch``/``height`` orient the nominal
   * electrode shell (height is applied in the array's local, pitched frame);
   * ``distance`` is the gap from the scalp. Markers live in a world-origin
   * group, so world coordinates are written directly.
   */
  project(
    head: Object3D,
    opts: { pitch: number; height: number; distance: number; brainCenter: Vector3 },
  ): void {
    const { pitch, height, distance, brainCenter: bc } = opts;
    head.updateWorldMatrix(true, true);

    const dir = new Vector3();
    const origin = new Vector3();
    const worldNormal = new Vector3();
    const normalMat = new Matrix3();
    const q = new Quaternion();

    for (const node of this.nodes.values()) {
      // Nominal world position = bc + R(pitch) * (nominal - bc + up*height).
      const local = node.nominal.clone().sub(bc).add(new Vector3(0, height, 0));
      local.applyAxisAngle(X_AXIS, pitch);
      const nominalWorld = local.add(bc);

      dir.copy(nominalWorld).sub(bc).normalize();
      if (dir.lengthSq() === 0) dir.set(0, 1, 0);
      origin.copy(bc).addScaledVector(dir, RAY_START_RADIUS);
      this.raycaster.set(origin, dir.clone().negate());

      const hits = this.raycaster.intersectObject(head, true);
      if (hits.length === 0) {
        // No surface found — fall back to the nominal shell position.
        node.mesh.position.copy(nominalWorld);
        node.light.position.copy(nominalWorld);
        node.label.position.copy(nominalWorld).addScaledVector(dir, LABEL_OFFSET);
        if (this.shape === "cone") {
          node.mesh.quaternion.copy(q.setFromUnitVectors(CONE_UP, dir));
        }
        continue;
      }

      const hit = hits[0];
      const point = hit.point;
      if (hit.face) {
        normalMat.getNormalMatrix(hit.object.matrixWorld);
        worldNormal.copy(hit.face.normal).applyMatrix3(normalMat).normalize();
        // Ensure the normal points outward (same side as the ray came from).
        if (worldNormal.dot(dir) < 0) worldNormal.negate();
      } else {
        worldNormal.copy(dir);
      }

      const surface = point.clone().addScaledVector(worldNormal, distance);
      if (this.shape === "cone") {
        // Base sits at the surface gap, apex points outward along the normal.
        node.mesh.position
          .copy(surface)
          .addScaledVector(worldNormal, CONE_HEIGHT / 2);
        node.mesh.quaternion.copy(q.setFromUnitVectors(CONE_UP, worldNormal));
      } else {
        node.mesh.position.copy(surface);
      }
      node.light.position.copy(surface).addScaledVector(worldNormal, 0.02);
      node.label.position.copy(surface).addScaledVector(worldNormal, LABEL_OFFSET);
    }
  }

  /**
   * Update from a frame: per-channel display values in [-1, 1]. Colour maps the
   * extremes to red/green and 0 (the channel's running mean) to black; the
   * light intensity is constant.
   */
  update(channels: string[], normalized: number[]): void {
    this.activeKeys.clear();
    for (let i = 0; i < channels.length; i++) {
      const key = normalize(channels[i]);
      const node = this.nodes.get(key);
      if (!node) continue;
      this.activeKeys.add(key);

      const isolated =
        this.debugElectrode !== null &&
        normalize(node.name) !== this.debugElectrode;

      const color = isolated
        ? BLACK
        : electrodeColor(normalized[i] ?? 0, this.colorScheme);
      node.material.emissive.copy(color);
      node.material.emissiveIntensity = 1.0;
      node.light.color.copy(color);
      node.light.intensity = this.indicatorsVisible && !isolated ? 1 : 0;
    }
    // Electrodes the stream doesn't populate: dim glow if "show all" is on.
    for (const [key, node] of this.nodes) {
      if (!this.activeKeys.has(key)) this.paintInactive(node);
    }
  }

  get channelNames(): string[] {
    return [...this.nodes.values()].map((n) => n.name);
  }
}

function normalize(name: string): string {
  return name.trim().toUpperCase();
}

/** A billboarded text sprite (canvas texture) for an electrode name. */
function makeLabelSprite(text: string): Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  const ctx = canvas.getContext("2d")!;
  ctx.font = "bold 72px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  // Dark outline so the name stays legible over the brain/head.
  ctx.lineWidth = 9;
  ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
  ctx.strokeText(text, 128, 70);
  ctx.fillStyle = "#eef3ff";
  ctx.fillText(text, 128, 70);

  const tex = new CanvasTexture(canvas);
  tex.minFilter = LinearFilter;
  const material = new SpriteMaterial({
    map: tex,
    transparent: true,
    depthWrite: false, // labels don't occlude each other / write depth
  });
  const sprite = new Sprite(material);
  sprite.scale.set(LABEL_W * DEFAULT_LABEL_SCALE, LABEL_H * DEFAULT_LABEL_SCALE, 1);
  return sprite;
}
