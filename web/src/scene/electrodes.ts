import {
  BufferGeometry,
  Color,
  ConeGeometry,
  Group,
  Matrix3,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PointLight,
  Quaternion,
  Raycaster,
  SphereGeometry,
  Vector3,
} from "three";
import type { ElectrodeMeta } from "../net/protocol";
import { redGreen, BAND_COLORS } from "./colormap";
import { ELECTRODE_LIGHT_LAYER } from "./brainHead";

interface ElectrodeNode {
  name: string;
  mesh: Mesh;
  light: PointLight;
  material: MeshStandardMaterial;
  nominal: Vector3; // nominal position on the ~unit electrode shell
}

export type ColorMode = "redgreen" | "band";
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
  private colorMode: ColorMode = "redgreen";
  private bandName = "alpha";
  private debugElectrode: string | null = null;
  private shape: ElectrodeShape = "sphere";

  private readonly sphereGeo = new SphereGeometry(0.04, 16, 12);
  private readonly coneGeo = new ConeGeometry(0.045, CONE_HEIGHT, 20);
  private readonly raycaster = new Raycaster();

  constructor(metas: ElectrodeMeta[]) {
    for (const meta of metas) {
      const material = new MeshStandardMaterial({
        color: 0x222831,
        emissive: 0x000000,
        roughness: 0.4,
      });
      const mesh = new Mesh(this.sphereGeo, material);
      // Markers are on the electrode-light layer too, so they stay lit when the
      // electrode lights are moved off the head's layer.
      mesh.layers.enable(ELECTRODE_LIGHT_LAYER);
      const nominal = new Vector3(...meta.position).multiplyScalar(1.04);
      mesh.position.copy(nominal);

      const light = new PointLight(0x000000, 0.0, 0.8, 2.0);
      light.position.copy(nominal);

      this.group.add(mesh, light);
      this.nodes.set(normalize(meta.name), {
        name: meta.name,
        mesh,
        light,
        material,
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

  setColorMode(mode: ColorMode): void {
    this.colorMode = mode;
  }

  setBand(name: string): void {
    this.bandName = name;
  }

  setDebugElectrode(name: string | null): void {
    this.debugElectrode = name ? normalize(name) : null;
  }

  /**
   * Control whether the electrode point lights illuminate the head. The lights
   * are always on ELECTRODE_LIGHT_LAYER (so the brain and markers — which share
   * that layer — are always lit), and layer 0 (the head's layer) is added only
   * when ``headLit`` is true.
   */
  setHeadLit(headLit: boolean): void {
    for (const n of this.nodes.values()) {
      n.light.layers.set(ELECTRODE_LIGHT_LAYER);
      if (headLit) n.light.layers.enable(0);
    }
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
    }
  }

  /** Update from a frame: channels + normalized values (+ optional bands). */
  update(
    channels: string[],
    normalized: number[],
    bands: Record<string, number[]>,
  ): void {
    const bandValues = bands[this.bandName];
    for (let i = 0; i < channels.length; i++) {
      const node = this.nodes.get(normalize(channels[i]));
      if (!node) continue;

      const isolated =
        this.debugElectrode !== null &&
        normalize(node.name) !== this.debugElectrode;

      let color: Color;
      let intensity: number;
      if (this.colorMode === "band" && bandValues) {
        const e = bandValues[i] ?? 0;
        color = (BAND_COLORS[this.bandName] ?? BAND_COLORS.alpha)
          .clone()
          .multiplyScalar(e);
        intensity = e * 2.5;
      } else {
        const v = normalized[i] ?? 0;
        color = redGreen(v);
        intensity = (v * 0.5 + 0.5) * 2.5;
      }

      if (isolated) {
        color = new Color(0x000000);
        intensity = 0;
      }

      node.material.emissive.copy(color);
      node.material.emissiveIntensity = 1.0;
      node.light.color.copy(color);
      node.light.intensity = this.indicatorsVisible ? intensity : 0;
      const scale = 1 + intensity * 0.15;
      node.mesh.scale.setScalar(scale);
    }
  }

  get channelNames(): string[] {
    return [...this.nodes.values()].map((n) => n.name);
  }
}

function normalize(name: string): string {
  return name.trim().toUpperCase();
}
