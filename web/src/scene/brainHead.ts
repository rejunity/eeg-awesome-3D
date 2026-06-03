import {
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshStandardMaterial,
  SphereGeometry,
  type IUniform,
} from "three";

/**
 * Procedural head + brain fallback (PLAN.md "procedural fallback").
 *
 * The real Unity assets (Realistic_White_Female_Head.obj, Realistic_Brain.fbx)
 * can be dropped in later as brain.glb / head.glb and loaded with GLTFLoader;
 * until then this gives the scene its shape: an OPAQUE head ellipsoid with an
 * alpha-cutout cutaway and a brain-like inner mesh.
 *
 * The head uses an alpha-cutout (discard) shader rather than transparency,
 * mirroring the original Unity HumanHead.shader (`alphatest:_Cutoff`, with
 * `alpha = -worldPos.y + sin(length(worldPos.xz))`). Fragments whose world Y is
 * above a wavy cut plane are discarded, so the head stays a cheap opaque draw
 * (no transmission/transparency render passes) while revealing the brain and
 * inner electrodes as the cut descends. The cut height is driven by the up/down
 * arrow keys (see controls/keyboard.ts).
 */

// Head world-space Y extents (sphere radius 1 scaled by 1.12 in Y, plus margin).
const CUT_TOP = 1.3; // cut at/above this -> whole head visible
const CUT_BOTTOM = -1.25; // cut at/below this -> head fully discarded

export class BrainHead {
  readonly group = new Group();
  readonly head: Mesh;
  readonly brain: Mesh;
  private headMaterial: MeshStandardMaterial;
  // Normalized cut control in [0, 1]: 1 = full head, 0 = fully cut away.
  private cut = 1.0;
  // Shared shader uniforms (wired in onBeforeCompile).
  private cutUniforms: { uCutHeight: IUniform<number>; uCutWave: IUniform<number> } = {
    uCutHeight: { value: CUT_TOP },
    uCutWave: { value: 0.05 },
  };

  constructor() {
    // Head: slightly egg-shaped, opaque, double-sided so the cutaway reveals
    // the inner surface.
    const headGeo = new SphereGeometry(1.0, 64, 48);
    headGeo.scale(0.92, 1.12, 1.05);
    this.headMaterial = new MeshStandardMaterial({
      color: 0xd9c6b8,
      roughness: 0.85,
      metalness: 0.0,
      side: 2, // DoubleSide
    });
    this._installCutShader(this.headMaterial);
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

  /**
   * Inject a world-space vertical cutout into a standard material via
   * onBeforeCompile: discard fragments above a wavy plane at uCutHeight.
   */
  private _installCutShader(material: MeshStandardMaterial): void {
    material.onBeforeCompile = (shader) => {
      shader.uniforms.uCutHeight = this.cutUniforms.uCutHeight;
      shader.uniforms.uCutWave = this.cutUniforms.uCutWave;

      // Pass world position to the fragment shader.
      shader.vertexShader = "varying vec3 vCutWorldPos;\n" + shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\n  vCutWorldPos = (modelMatrix * vec4(transformed, 1.0)).xyz;",
      );

      // Discard above the (wavy) cut plane. The sin() term mirrors the Unity
      // shader's `+ sin(length(worldPos.xz))` so the cut edge undulates.
      shader.fragmentShader =
        "varying vec3 vCutWorldPos;\nuniform float uCutHeight;\nuniform float uCutWave;\n" +
        shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace(
        "#include <clipping_planes_fragment>",
        "#include <clipping_planes_fragment>\n" +
          "  float cutLine = uCutHeight + uCutWave * sin(length(vCutWorldPos.xz) * 6.2831);\n" +
          "  if (vCutWorldPos.y > cutLine) discard;",
      );
    };
    material.needsUpdate = true;
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

  /**
   * Set the vertical cutaway. ``value`` is normalized [0, 1]:
   * 1 = full head, 0 = head fully cut away (revealing the brain).
   * Replaces the old opacity control — the head is opaque now.
   */
  setCutaway(value: number): void {
    this.cut = Math.min(1, Math.max(0, value));
    this.cutUniforms.uCutHeight.value =
      CUT_BOTTOM + (CUT_TOP - CUT_BOTTOM) * this.cut;
  }

  /** Backwards-compatible alias: presets/GUI used to call setHeadOpacity. */
  setHeadOpacity(value: number): void {
    this.setCutaway(value);
  }

  setHeadVisible(visible: boolean): void {
    this.head.visible = visible;
  }

  setBrainVisible(visible: boolean): void {
    this.brain.visible = visible;
  }

  /** Adjust the cutaway (arrow keys), echoing Unity's _Cutoff. */
  adjustCutoff(delta: number): void {
    this.setCutaway(this.cut + delta);
  }
}
