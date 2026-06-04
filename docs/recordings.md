# Test EEG recordings

This project can replay real EEG recordings as an LSL source for testing
without hardware (see `eegvis fetch-sample` / `eegvis play-file`). This document
records where the sample data comes from and how its channels map onto our CGX
layout, and surveys other public datasets we could use.

## Sample recording: `S001R03.edf`

| | |
|---|---|
| **Dataset** | EEG Motor Movement/Imagery Database (eegmmidb), v1.0.0 |
| **Source** | PhysioNet — https://physionet.org/content/eegmmidb/1.0.0/ |
| **File** | `S001R03.edf` — subject 1, run 3 |
| **Channels** | 64 EEG, modified 10‑10 montage |
| **Sampling rate** | 160 Hz |
| **Format** | EDF+ (one extra "EDF Annotations" channel, dropped on import) |
| **Units** | microvolts |
| **License** | Open Data Commons Attribution License v1.0 (attribution required) |

The dataset has 109 subjects, each with 14 runs: `R01` (eyes-open baseline),
`R02` (eyes-closed baseline), and `R03`–`R14` (motor movement/imagery tasks —
opening/closing fists or feet). We default to `S001R03` (a task run) because it
contains real movement-related activity, but any subject/run works:

```bash
eegvis fetch-sample --subject 1 --run 3      # default
eegvis fetch-sample --subject 42 --run 8
```

**Attribution / citation** (required by the licence):

- Schalk, G., McFarland, D.J., Hinterberger, T., Birbaumer, N., Wolpaw, J.R.
  *BCI2000: A General-Purpose Brain-Computer Interface (BCI) System.* IEEE
  Transactions on Biomedical Engineering 51(6):1034–1043, 2004.
- Goldberger, A., et al. *PhysioBank, PhysioToolkit, and PhysioNet.*
  Circulation 101(23):e215–e220, 2000.

## How it's prepared

`eegvis fetch-sample` downloads the EDF, then:

1. Parses it with our dependency-free EDF reader (`eegvis/recordings/edf.py`),
   converting digital samples to physical microvolts and dropping the EDF+
   annotations channel.
2. Maps channels onto the CGX **Quick32r** EEG montage (29 channels) —
   `eegvis/recordings/mapping.py`.
3. Saves a compact `recordings/S001R03_cgx.npz` (data + channel names + rate).

The `recordings/` directory is git-ignored; data is fetched on demand.

## Channel mapping

Names are normalized for matching by lower-casing and stripping non-alphanumeric
characters, so the dataset's modified‑10‑10 labels (trailing dots, mixed case)
line up with our CGX names. **All 29 CGX Quick32r EEG channels are matched** by
this 64‑channel dataset (nothing zero-filled):

| CGX channel | eegmmidb label | CGX channel | eegmmidb label |
|---|---|---|---|
| AF7 | `Af7.` | P4  | `P4..` |
| Fpz | `Fpz.` | P7  | `P7..` |
| F7  | `F7..` | P8  | `P8..` |
| Fz  | `Fz..` | Pz  | `Pz..` |
| T7  | `T7..` | PO7 | `Po7.` |
| FC6 | `Fc6.` | T8  | `T8..` |
| Fp1 | `Fp1.` | C3  | `C3..` |
| F4  | `F4..` | Fp2 | `Fp2.` |
| C4  | `C4..` | F3  | `F3..` |
| Oz  | `Oz..` | F8  | `F8..` |
| CP6 | `Cp6.` | FC5 | `Fc5.` |
| Cz  | `Cz..` | AF8 | `Af8.` |
| PO8 | `Po8.` | | |
| CP5 | `Cp5.` | | |
| O2  | `O2..` | | |
| O1  | `O1..` | | |
| P3  | `P3..` | | |

Channels are emitted in CGX Quick32r order. Any CGX channel absent from a source
recording is zero-filled and reported by `fetch-sample`.

## Other public datasets

Our EDF reader handles any EDF/EDF+ file, so `eegvis play-file some.edf` works
on any EDF dataset (it maps onto the CGX montage the same way). Other container
formats (BrainVision, GDF, BDF, EEGLAB `.set`) would need an additional reader.

> Note: 64‑channel eegmmidb **already covers all 29 CGX channels**, so "more
> channels" doesn't improve CGX coverage — it only matters if we later extend
> beyond the CGX montage. For variety now, just fetch other subjects/runs.

| Dataset | Channels | Montage | Format | License | Works today? |
|---|---|---|---|---|---|
| **eegmmidb** (current) | 64 | 10‑10 | EDF+ | ODC‑BY 1.0 | ✅ all 29 CGX |
| PhysioNet **EEG Mental Arithmetic** (eegmat) | 21 | 10‑20 | EDF | ODC‑BY 1.0 | ✅ (~19 CGX) via `play-file` |
| PhysioNet **Auditory evoked / EEG biometric** | 64 | 10‑10 | EDF | ODC‑BY 1.0 | ✅ via `play-file` |
| **MPI‑Leipzig LEMON** | 62 | 10‑10 | BrainVision | CC‑BY‑NC | ⚠️ needs BrainVision reader |
| **BNCI Horizon 2020** (e.g. BCI‑IV‑2a) | 22–64 | 10‑20 | GDF | varies (open) | ⚠️ needs GDF reader |
| **OpenNeuro** (many BIDS datasets) | 64–256 | 10‑10/EGI | BrainVision/EDF/BDF/SET | mostly CC0/CC‑BY | mixed (EDF ✅) |
| **TUH EEG Corpus** | 19–31 | 10‑20 | EDF | registration required | ✅ format, but gated |
| CHB‑MIT Scalp EEG | 23 | bipolar 10‑20 | EDF | ODC‑BY 1.0 | ❌ bipolar pairs, not single electrodes |
| Healthy Brain Network (HBN) | 128 | EGI (E1…E128) | EGI/SET | open (DUA) | ❌ EGI naming needs montage conversion |

**Recommendations**

- For **more variety with zero new code**: additional eegmmidb subjects/runs, or
  the PhysioNet **eegmat** (10‑20, EDF) — download its `.edf` and
  `eegvis play-file Subject00.edf`.
- For **denser 10‑10 coverage** (if we extend past CGX): **LEMON** (62‑ch
  resting state) is excellent but is BrainVision — would need a `.vhdr/.eeg`
  reader (or a one-time MNE-based conversion to our `.npz`).
- **Avoid** bipolar (CHB‑MIT) and high-density EGI (HBN) montages: their
  channel labels don't map onto single 10‑20 electrode positions without extra
  montage work.
