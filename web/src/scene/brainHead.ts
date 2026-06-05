import {
  Box3,
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshStandardMaterial,
  SphereGeometry,
  Vector3,
  type IUniform,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

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
// Cutaway range in world Y, matched to the head's extent (~[-3.25, 0.47]).
const CUT_TOP = 0.6; // cut at/above this -> whole head visible
const CUT_BOTTOM = -3.3; // cut at/below this -> head fully discarded

// Brain placement, fitted anatomically INSIDE the fixed head (head world bbox
// ~ x[-1.65,1.75], y[-3.25,0.47], z[-1.30,1.18]). The brain is scaled up to
// fill the cranium (front-to-back nearly fills the skull depth), pitched so the
// frontal lobe tilts down following the cranial base, and lowered so it nestles
// in the upper skull with its crown just under the head's. All three are
// tunable knobs — adjust against a screenshot.
const BRAIN_SCALE = 1.135; // uniform scale of brain.glb (glb max dim ~1.32)
const BRAIN_PITCH = -0.1; // radians about X (+ = frontal lobe tilts down)
// Head placement, derived to match the head→brain relationship in the Unity
// scene (`_CGX_Main_Scene.unity`), with the brain centred on the origin.
//
// Reconstructed from the Unity prefab transforms + model import scales:
//   head:  pos (0,-57.85,0), rot 180°Y, scale 1   (OBJ, globalScale 1)
//   brain: pos (-0.15,6.5,0.14), rot ~180°Y, scale 0.54  (FBX, globalScale 1000)
// The FBX asset scale (k≈6) is the one value not directly readable from the
// scene; it's pinned by the brain crown meeting the skull crown (consistent
// with the Unity render). From those world bounding boxes, the head centre sits
// at this offset from the brain centre (in brain-size units) and the head is
// this many times the brain's size:
//   head_centre - brain_centre = (0.046, -1.301, -0.046) * brain_size
//   head_size / brain_size (height) = 3.488
// Applied to our origin-centred brain (BRAIN_TARGET_SIZE) these become:
const HEAD_SCALE_REL = 0.254; // uniform head scale (matches Unity head/brain ratio)
// Head bbox centre in world space (brain centre = origin). The head drops below
// the brain so the brain sits high in the cranium and the face extends down,
// exactly as in Unity. NB: per request this ignores electrode positions.
// X is forced to 0 so the head's midline aligns with the electrode array
// (which is symmetric about x=0); the original Unity X shift (~0.046) is dropped.
const HEAD_CENTER = new Vector3(0, -1.388, -0.057);
// Brain bbox centre in world space — inside the cranium of the fixed head, with
// the crown just below the head's (head crown y≈0.47).
// X forced to 0 to share the electrode/head midline (drops the Unity X shift).
const BRAIN_CENTER = new Vector3(0, -0.55, -0.05);

export class BrainHead {
  readonly group = new Group();
  // Containers so we can swap the procedural placeholders for loaded models.
  readonly head = new Group();
  readonly brain = new Group();
  private brainMaterial: MeshStandardMaterial;
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
    // Procedural ellipsoid fallback, replaced by the real model once it loads.
    this.head.add(new Mesh(headGeo, this.headMaterial));

    // Shared brain material (pinkish, slightly emissive) used by both the
    // procedural fallback and the loaded model so the look stays consistent.
    this.brainMaterial = new MeshStandardMaterial({
      color: 0xc98b9a,
      roughness: 0.6,
      metalness: 0.05,
      emissive: 0x3a1f28,
      emissiveIntensity: 0.4,
    });

    // Procedural lumpy fallback, shown immediately and replaced by the real
    // model (Realistic_Brain.fbx -> brain.glb) once it loads.
    const brainGeo = new IcosahedronGeometry(0.66, 4);
    this._displace(brainGeo);
    this.brain.add(new Mesh(brainGeo, this.brainMaterial));
    // The brain group carries the anatomical placement: position = centre,
    // rotation.x = pitch, scale = BRAIN_SCALE. The loaded model is recentred on
    // the group origin so scale/pitch act about the brain centre. Scale and
    // pitch live on the group so they can be tweaked at runtime (GUI).
    this.brain.position.copy(BRAIN_CENTER);
    this.brain.rotation.x = BRAIN_PITCH;
    this.brain.scale.setScalar(BRAIN_SCALE);

    this.group.add(this.head, this.brain);
    this._loadHeadModel();
    this._loadBrainModel();
  }

  /**
   * Load the converted head model (Realistic_White_Female_Head.obj -> head.glb,
   * decimated) and swap it in for the procedural ellipsoid. Recentred to the
   * origin and scaled to HEAD_TARGET_SIZE so it lines up with the electrode
   * shell; the cut shader (headMaterial) is applied so the cutaway still works.
   * If the model points the wrong way, flip with model.rotateY(Math.PI).
   */
  private _loadHeadModel(): void {
    new GLTFLoader().load(
      "models/head.glb",
      (gltf) => {
        const model = gltf.scene;
        const box = new Box3().setFromObject(model);
        const center = box.getCenter(new Vector3());

        // Unity-derived uniform scale and placement relative to the brain.
        const scale = HEAD_SCALE_REL;
        model.scale.setScalar(scale);
        // Position so the head's bbox centre lands at HEAD_CENTER.
        model.position.set(
          HEAD_CENTER.x - center.x * scale,
          HEAD_CENTER.y - center.y * scale,
          HEAD_CENTER.z - center.z * scale,
        );
        model.traverse((obj) => {
          const mesh = obj as Mesh;
          if (mesh.isMesh) {
            mesh.material = this.headMaterial;
            // The decimated head scan ships without normals; compute smooth
            // normals from the (welded) geometry so it lights correctly.
            if (!mesh.geometry.getAttribute("normal")) {
              mesh.geometry.computeVertexNormals();
            }
          }
        });

        this.head.clear();
        this.head.add(model);
      },
      undefined,
      (err) => {
        console.warn("head.glb failed to load; using procedural head", err);
      },
    );
  }

  /**
   * Load the converted brain model and swap it in for the procedural fallback.
   * The model is recentred within the brain group and uniformly scaled by
   * BRAIN_SCALE; the group then applies the anatomical centre + pitch so the
   * brain sits inside the cranium. On any error the procedural brain remains.
   */
  private _loadBrainModel(): void {
    new GLTFLoader().load(
      "models/brain.glb",
      (gltf) => {
        const model = gltf.scene;

        const box = new Box3().setFromObject(model);
        const center = box.getCenter(new Vector3());

        // Recentre the model on the group origin (scale 1); the brain group
        // applies position/pitch/scale so they all act about the brain centre.
        model.position.set(-center.x, -center.y, -center.z);

        model.traverse((obj) => {
          const mesh = obj as Mesh;
          if (mesh.isMesh) mesh.material = this.brainMaterial;
        });

        this.brain.clear();
        this.brain.add(model);
      },
      undefined,
      (err) => {
        console.warn("brain.glb failed to load; using procedural brain", err);
      },
    );
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

  /** Runtime brain scale (uniform), about the brain centre. */
  setBrainScale(scale: number): void {
    this.brain.scale.setScalar(scale);
  }

  /** Runtime brain pitch in radians (about X, through the brain centre). */
  setBrainPitch(radians: number): void {
    this.brain.rotation.x = radians;
  }

  /** World-space brain centre (pivot for the brain and the electrode array). */
  get brainCenter(): Vector3 {
    return this.brain.position.clone();
  }

  /** Default knob values, so the GUI can initialise its sliders. */
  static readonly defaults = {
    brainScale: BRAIN_SCALE,
    brainPitch: BRAIN_PITCH,
  };

  setBrainVisible(visible: boolean): void {
    this.brain.visible = visible;
  }

  /** Adjust the cutaway (arrow keys), echoing Unity's _Cutoff. */
  adjustCutoff(delta: number): void {
    this.setCutaway(this.cut + delta);
  }
}
