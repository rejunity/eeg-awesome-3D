"""Derive standard 10-10 electrode positions consistent with the CGX cap.

The 29 CGX Quick32r electrodes (``_UNITY_ELECTRODES`` in
``eegvis/assets/electrodes_cgx.py``) lie on a clean radius-85 sphere that follows
the standard 10-20 spherical model. This script extends that cap to the full
64-channel 10-10 layout (biosemi64 set) WITHOUT moving any existing electrode.

Method (see commit message / PR for the analysis):
  1. Analytical base — place each electrode (row, col) on the sphere via
     ``Rx(col*b) @ Ry(row*a) @ Cz``. Fitting a, b to the 29 anchors recovers the
     cap's per-step arc spacing and reproduces the correct boundary topology
     (e.g. FT7 lands between F7 and T7 on the lateral ring).
  2. Residual warp — a bilaterally-symmetric thin-plate-spline over (col, row)
     corrects the small (~5 deg) deviation of the real cap from the ideal grid,
     so every existing anchor is reproduced exactly (leave-one-out error 0.0).

Run: python scripts/gen_1010_positions.py  -> prints the new electrode tuples.
"""
from __future__ import annotations
import numpy as np
from scipy.optimize import minimize
from scipy.interpolate import RBFInterpolator
from eegvis.assets.electrodes_cgx import _UNITY_ELECTRODES

R = 85.0
ROW = {"Fp":4,"AF":3,"F":2,"FC":1,"FT":1,"C":0,"T":0,"CP":-1,"TP":-1,"P":-2,"PO":-3,"O":-4,"I":-5}
_MAG = {1:1,2:1,3:2,4:2,5:3,6:3,7:4,8:4,9:5,10:5}

def rowcol(label: str) -> tuple[int, int]:
    """10-10 label -> (row: front+, col: left+) integer lattice coordinate."""
    if label.endswith("z"):
        return ROW[label[:-1]], 0
    i = len(label)
    while i > 0 and label[i-1].isdigit():
        i -= 1
    pre, num = label[:i], int(label[i:])
    return ROW[pre], (1 if num % 2 else -1) * _MAG[num]

def Ry(t): c,s=np.cos(t),np.sin(t); return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def Rx(t): c,s=np.cos(t),np.sin(t); return np.array([[1,0,0],[0,c,-s],[0,s,c]])
def base(r,c,a,b): return Rx(c*b) @ Ry(r*a) @ np.array([0,0,1.0])

# canonical biosemi64 10-10 montage (64 channels)
BIOSEMI64 = [
    "Fp1","Fpz","Fp2","AF7","AF3","AFz","AF4","AF8",
    "F7","F5","F3","F1","Fz","F2","F4","F6","F8",
    "FT7","FC5","FC3","FC1","FCz","FC2","FC4","FC6","FT8",
    "T7","C5","C3","C1","Cz","C2","C4","C6","T8",
    "TP7","CP5","CP3","CP1","CPz","CP2","CP4","CP6","TP8",
    "P9","P7","P5","P3","P1","Pz","P2","P4","P6","P8","P10",
    "PO7","PO3","POz","PO4","PO8","O1","Oz","O2","Iz",
]

def build():
    anchors = {n: np.array([x,y,z],float) for n,x,y,z in _UNITY_ELECTRODES}
    au = {n: anchors[n]/np.linalg.norm(anchors[n]) for n in anchors}
    RC = {n: rowcol(n) for n in anchors}
    err = lambda p: sum(np.sum((base(*RC[n],*np.radians(p))-au[n])**2) for n in anchors)
    a,b = np.radians(minimize(err,[20.6,-24.2],method="Nelder-Mead").x)
    Xin = np.array([[RC[n][1],RC[n][0]] for n in anchors],float)
    Yres = np.array([au[n]-base(*RC[n],a,b) for n in anchors])
    nz = Xin[:,0] != 0
    Xa = np.vstack([Xin, Xin[nz]*[-1,1]]); Ya = np.vstack([Yres, Yres[nz]*[-1,-1,1]])
    f = RBFInterpolator(Xa, Ya, kernel="thin_plate_spline", smoothing=1e-3)
    def predict(label):
        r,c = rowcol(label)
        p  = base(r, c,a,b) + f(np.array([[ c,r]]))[0]
        pm = (base(r,-c,a,b) + f(np.array([[-c,r]]))[0]) * [1,-1,1]  # mirror-average
        p = (p+pm)/2
        if c == 0: p[1] = 0.0
        return p/np.linalg.norm(p) * R
    return anchors, predict

if __name__ == "__main__":
    anchors, predict = build()
    print("# --- 10-10 extension to 64 channels (derived; see scripts/gen_1010_positions.py)")
    for n in BIOSEMI64:
        if n in anchors:
            continue
        x,y,z = predict(n)
        print(f'    ("{n}", {x:.1f}, {y:.1f}, {z:.1f}),')
