import {
  Color,
  Group,
  Mesh,
  MeshStandardMaterial,
  PointLight,
  SphereGeometry,
  Vector3,
} from "three";
import type { ElectrodeMeta } from "../net/protocol";
import { redGreen, BAND_COLORS } from "./colormap";

interface ElectrodeNode {
  name: string;
  mesh: Mesh;
  light: PointLight;
  material: MeshStandardMaterial;
  basePos: Vector3;
}

export type ColorMode = "redgreen" | "band";

/**
 * Electrode markers placed by CGX label. Each marker is a small sphere with a
 * point light whose colour/intensity is driven by the latest processed value
 * (red→green parity from Unity) or by band energy.
 *
 * Channel names are matched case/space-insensitively; missing channels are
 * left dark. A debug mode isolates one electrode (the old `debugElectrode`).
 */
export class Electrodes {
  readonly group = new Group();
  private nodes = new Map<string, ElectrodeNode>();
  private indicatorsVisible = true;
  private colorMode: ColorMode = "redgreen";
  private bandName = "alpha";
  private debugElectrode: string | null = null;

  constructor(metas: ElectrodeMeta[]) {
    const geo = new SphereGeometry(0.035, 16, 12);
    for (const meta of metas) {
      const material = new MeshStandardMaterial({
        color: 0x222831,
        emissive: 0x000000,
        roughness: 0.4,
      });
      const mesh = new Mesh(geo, material);
      // Push markers slightly out along the scalp normal.
      const p = new Vector3(...meta.position).multiplyScalar(1.04);
      mesh.position.copy(p);

      const light = new PointLight(0x000000, 0.0, 0.8, 2.0);
      light.position.copy(p).multiplyScalar(1.02);

      this.group.add(mesh, light);
      this.nodes.set(normalize(meta.name), {
        name: meta.name,
        mesh,
        light,
        material,
        basePos: p.clone(),
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
