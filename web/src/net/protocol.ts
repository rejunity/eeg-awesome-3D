// Shared payload types — mirror eegvis/models.py. Keep in sync with the backend.

export interface StreamInfo {
  name: string;
  type: string;
  source_id: string | null;
  channel_count: number;
  sample_rate: number;
  channel_names: string[];
  channel_types: string[] | null;
}

export interface StatusPayload {
  type: "status";
  schema_version: number;
  connected: boolean;
  mode: string; // "lsl" | "synthetic" | "disconnected"
  message: string | null;
  stream: StreamInfo | null;
}

export interface FFTBlock {
  freqs: number[];
  values: number[][]; // [channel][bin]
}

export interface AsymmetryBlock {
  regions: string[];
  // bands[band][region] in [-1,1]; positive = right hemisphere stronger.
  bands: Record<string, number[]>;
}

export interface RegionPowerBlock {
  regions: string[];
  // bands[band][region] >= 0; mean band power per lobe.
  bands: Record<string, number[]>;
}

export interface QualityInfo {
  samples_received: number;
  dropped_chunks: number;
  latency_ms: number;
}

export interface EEGFramePayload {
  type: "eeg_frame";
  schema_version: number;
  frame_index: number;
  timestamp: number;
  sample_rate: number;
  channels: string[];
  raw: number[];
  // All raw EEG samples in this chunk: samples[i] = per-channel values.
  samples: number[][];
  // All EEG samples after the global filter chain (== samples if no filter).
  filtered_samples: number[][];
  latest: number[];
  normalized: number[];
  bands: Record<string, number[]>;
  // Generic per-channel scalar features keyed by name: features[name][channel].
  features: Record<string, number[]>;
  fft: FFTBlock | null;
  asymmetry: AsymmetryBlock | null;
  region_power: RegionPowerBlock | null;
  short_fourier: Record<string, number[]> | null;
  quality: QualityInfo;
}

export interface StreamDescriptor {
  name: string;
  source_id: string | null;
  type: string;
  channel_count: number;
  sample_rate: number;
}

export interface StreamsPayload {
  type: "streams";
  schema_version: number;
  streams: StreamDescriptor[];
  current: string | null; // selected source_id ("synthetic" for the generator)
}

export type ServerMessage = StatusPayload | EEGFramePayload | StreamsPayload;

export function isStatus(m: ServerMessage): m is StatusPayload {
  return m.type === "status";
}

export function isFrame(m: ServerMessage): m is EEGFramePayload {
  return m.type === "eeg_frame";
}

export function isStreams(m: ServerMessage): m is StreamsPayload {
  return m.type === "streams";
}

export interface ElectrodeMeta {
  name: string;
  position: [number, number, number];
}

export interface ElectrodeResponse {
  scale: number;
  electrodes: ElectrodeMeta[];
}
