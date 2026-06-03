import { DoubleSide, Mesh, MeshBasicMaterial, PlaneGeometry, Texture } from "three";

/**
 * A flat HUD-style plane in the scene that shows one of the dynamic textures
 * (EEG trace, band matrix, FFT). Mirrors Unity's full-screen DisplayEEG, but
 * as a billboard panel behind the head so all modes share one surface.
 */
export class DisplayPanel {
  readonly mesh: Mesh;
  private material: MeshBasicMaterial;

  constructor(width = 3.2, height = 1.0) {
    this.material = new MeshBasicMaterial({
      transparent: true,
      side: DoubleSide,
      depthWrite: false,
    });
    this.mesh = new Mesh(new PlaneGeometry(width, height), this.material);
    this.mesh.position.set(0, 1.7, -1.2);
    this.mesh.visible = false;
  }

  setTexture(texture: Texture): void {
    this.material.map = texture;
    this.material.needsUpdate = true;
  }

  setVisible(visible: boolean): void {
    this.mesh.visible = visible;
  }

  get visible(): boolean {
    return this.mesh.visible;
  }
}
