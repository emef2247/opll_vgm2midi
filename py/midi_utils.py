#!/usr/bin/env python3
"""Convert VGM (YM2413/OPLL) traces to Standard MIDI File (SMF format 0).
Usage:
    python vgm2midi.py <vgm_file> [--outdir <dir>] [--debug]

Default output (no --debug):
    Generate <stem>.mid and <stem>.user_voice.json (if user patches exist)

With --debug:
    The <stem>.mid file and the raw log/trace CSV files.

Example:
    python vgm2midi.py test.vgm
"""

from __future__ import annotations

import sys
import os
import json
import struct
from dataclasses import dataclass
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, 'py'))

from vgm_reader import parse_vgm

from opll import (
    RHYTHM_CH_MAP,
    NUM_CH,
    _assign_voice_ids,
    _build_segments,
    _opll_note,
    _ym2413_patch_to_mgsdrv,
    parse_opll_regs_for_rhythm,
)

from segment_utils import _Segment

DEFAULT_PPQ = 480

# User patches are assigned GM programs starting from this value (0-indexed).
# Programs 0-14 correspond to OPLL presets 1-15 via OPLL_TO_GM_PROGRAM.
# Programs 15-19 are reserved for rhythm channels (bd/sd/tom/tc/hh) in MS2
# convention (INST 16-20).  User patches therefore start at program 20
# (= GM program 21 in 1-indexed / musician notation).
_USER_VOICE_FIRST_GM_PROGRAM = 20

# All-zero patch sentinel: inst=0 with no register writes.
# Fixed to GM 127 (Gunshot) to make it clearly audible / obviously wrong.
_ZERO_PATCH = bytes(8)

# ------------------------------------------------------------
# OPLL (YM2413) Rhythm Instruments (BD/SD/TOM/TC/HH/CYM)
# ------------------------------------------------------------
# BD  : Bass Drum
# SD  : Snare Drum
# TOM : Tom
# TC  : Top Cymbal
# HH  : Hi-Hat
# CYM : Cymbal


RHYTHM_TO_GM_NOTE = {
    "bd": 35,
    "sd": 38,
    "tom": 41,
    "tc": 49,
    "hh": 42,
}

# RX21 Instrument key number
# BD 45 "A1"
# TOM3 48 "A1"
# TOM2 50 "C2"
# SD   52 "E2"
# TOM1 53 "F2"
# CLAPS 54 "F#2"
# HH CLOSED 57 "A2"
# HH OPEN   59 "B2"
# CYM   60 "C3"

RHYTHM_VOICE_ID_MAP_RX21 = {
    "bd": 45,
    "sd": 52,
    "tom": 50,   # TOM2 を基準にするなら 50
    "tc": 53,    # TOM1 or TOM3 に割り当てるなら変更可
    "hh": 57,    # Closed HH
    "cym": 60,   # Crash
}

RHYTHM_VOICE_ID_MAP_RX21_BASE = {
    "bd": 45,  # 固定
    "sd": 52,  # 固定
}


SCALE_TO_SEMITONE = {
    "c": 0,
    "c+": 1,
    "d": 2,
    "d+": 3,
    "e": 4,
    "f": 5,
    "f+": 6,
    "g": 7,
    "g+": 8,
    "a": 9,
    "a+": 10,
    "b": 11,
}


@dataclass(frozen=True)
class MidiEvent:
    tick: int
    order: int
    data: bytes

MID_LOW  = 0
MID_HIGH = 127
TC_TO_CYM_THRESHOLD = 55
HH_OPEN_THRESHOLD = 58

# ---------------------------------------------------------------------------
# GM Rhythm Map Helpers
# ---------------------------------------------------------------------------
# GM Drum Notes
GM_TOM_LOW  = 41
GM_TOM_MID  = 45
GM_TOM_HIGH = 48
GM_HH_CLOSED = 42
GM_HH_OPEN   = 46
GM_CYM       = 49

def select_gm_tom(scale_raw):
    scale = normalize_scale(scale_raw)
    if scale < MID_LOW:
        return GM_TOM_LOW
    elif scale < MID_HIGH:
        return GM_TOM_MID
    else:
        return GM_TOM_HIGH

def map_gm_drum(kind: str, scale_raw) -> int:
    scale = normalize_scale(scale_raw)

    if kind == "bd":
        return 35
    if kind == "sd":
        return 38

    if kind == "tom":
        return select_gm_tom(scale)

    if kind == "tc":
        if scale > TC_TO_CYM_THRESHOLD:
            return GM_CYM
        else:
            return select_gm_tom(scale)

    if kind == "hh":
        if scale < HH_OPEN_THRESHOLD:
            return GM_HH_CLOSED
        else:
            return GM_HH_OPEN

    if kind == "cym":
        return GM_CYM

    return 38


def normalize_scale(scale_raw) -> int:
    """
    scale_raw が:
      - int の場合 → そのまま返す
      - 'c+' などの文字列 → SCALE_TO_SEMITONE で変換
      - None / 不正値 → 0 にフォールバック
    """
    if isinstance(scale_raw, int):
        return scale_raw

    if isinstance(scale_raw, str):
        return SCALE_TO_SEMITONE.get(scale_raw.lower(), 0)

    return 0

# ---------------------------------------------------------------------------
# RX21 Rhythm Map Helpers
# ---------------------------------------------------------------------------
def select_rx21_tom(scale_raw) -> int:
    scale = normalize_scale(scale_raw)

    if scale < MID_LOW:
        return 48  # TOM3
    elif scale < MID_HIGH:
        return 50  # TOM2
    else:
        return 53  # TOM1

def map_rx21_drum(kind: str, scale_raw) -> int:
    scale = normalize_scale(scale_raw)

    if kind == "bd":
        return 45
    if kind == "sd":
        return 52

    if kind == "tom":
        return select_rx21_tom(scale)

    if kind == "tc":
        if scale > TC_TO_CYM_THRESHOLD:
            return 60  # CYM
        else:
            return select_rx21_tom(scale)

    if kind == "hh":
        if scale < HH_OPEN_THRESHOLD:
            return 57  # Closed
        else:
            return 59  # Open

    return 52

# ---------------------------------------------------------------------------
# User voice map helpers
# ---------------------------------------------------------------------------

def _user_voice_map_path(output_dir: str, stem: str) -> str:
    """Return the path for <stem>.user_voice.json beside the .mid output."""
    return os.path.join(output_dir, f"{stem}.user_voice.json")


def _is_zero_patch(patch_bytes: bytes) -> bool:
    """Return True if the patch is all-zero (no register writes occurred)."""
    return patch_bytes == _ZERO_PATCH


def _format_user_patch_lines(at_v_num: int, patch_bytes: bytes, gm_prog: int) -> list[str]:
    """Return human-readable description lines for a single user patch.

    All-zero patches (no register written) are flagged as unused with a
    single summary line instead of the full register decode.

    Normal format::

        User patch Inst 20 (1-indexed:21) -> GM program 20
        Inst 20: 'User patch v15' regs = 21 1B C2 F0 01 14 74 11
            TL=27 FB=4
            MO: AR= 2 DR= 1 SL=12 RR= 2 KL= 0 MT= 1 AM= 0 VB= 0 EG= 1 KR= 0 DT= 0
            CA: AR=15 DR= 4 SL= 0 RR= 5 KL= 0 MT= 1 AM= 0 VB= 1 EG= 0 KR= 1 DT= 0

    All-zero format::

        User patch Inst 127 (1-indexed:128) -> GM program 127  (unused - no register written)
        Inst 127: 'User patch v15' regs = 00 00 00 00 00 00 00 00  [all zero]
    """
    regs_str = ' '.join(f'{b:02X}' for b in patch_bytes)
    if _is_zero_patch(patch_bytes):
        return [
            f"User patch Inst {gm_prog} (1-indexed:{gm_prog + 1}) -> GM program {gm_prog}"
            f"  (unused - no register written)",
            f"Inst {gm_prog}: 'User patch v{at_v_num}' regs = {regs_str}  [all zero]",
        ]
    d = _ym2413_patch_to_mgsdrv(patch_bytes)
    tl, fb = d['tl'], d['fb']
    m = d['mod']   # (ar, dr, sl, rr, kl, mt, am, vb, eg, kr, dt)
    c = d['car']
    return [
        f"User patch Inst {gm_prog} (1-indexed:{gm_prog + 1}) -> GM program {gm_prog}",
        f"Inst {gm_prog}: 'User patch v{at_v_num}' regs = {regs_str}",
        f"\tTL={tl:2d} FB={fb}",
        f"\tMO: AR={m[0]:2d} DR={m[1]:2d} SL={m[2]:2d} RR={m[3]:2d} "
        f"KL={m[4]} MT={m[5]:2d} AM={m[6]} VB={m[7]} EG={m[8]} KR={m[9]} DT={m[10]}",
        f"\tCA: AR={c[0]:2d} DR={c[1]:2d} SL={c[2]:2d} RR={c[3]:2d} "
        f"KL={c[4]} MT={c[5]:2d} AM={c[6]} VB={c[7]} EG={c[8]} KR={c[9]} DT={c[10]}",
    ]


def _load_user_voice_map(path: str) -> dict[str, int]:
    """Load patch_hex -> GM program (0-indexed) mapping from JSON.

    Returns an empty dict if the file does not exist or cannot be parsed.
    Keys are lower-case 16-character hex strings.
    Values are 0-indexed GM program numbers (0-127).
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        result: dict[str, int] = {}
        for k, v in data.items():
            if k.startswith("_"):          # skip comment/info keys
                continue
            if isinstance(k, str) and isinstance(v, int):
                result[k.lower()] = max(0, min(127, v))
        return result
    except Exception:
        return {}


def _save_user_voice_map(
    path: str,
    mapping: dict[str, int],
    user_patches: dict[int, bytes],
    at_v_to_gm: dict[int, int],
) -> None:
    """Save patch_hex -> GM program (0-indexed) mapping to JSON.

    Adds:
    - ``_comment``: format explanation for the user.
    - ``_voice_info``: dict of patch_hex -> list[str] with decoded OPLL register
      details for each user patch (at the end of the file for reference).
    """
    out: dict = {
        "_comment": (
            "OPLL user-patch to GM program mapping for vgm2midi.py. "
            "Keys are 8-byte OPLL patch data in hex (16 chars). "
            "Values are 0-indexed GM program numbers "
            "(0=Acoustic Grand Piano ... 127=Gunshot; "
            "i.e. subtract 1 from the 1-indexed program number shown in most DAWs). "
            "Edit values to remap user patches to any GM instrument. "
            "New patches discovered on the next run are appended automatically. "
            "All-zero patches (no register written) are fixed to GM 127 (Gunshot) "
            "and marked as unused."
        ),
    }
    out.update(mapping)

    # Build _voice_info: patch_hex -> decoded register lines (for reference / editing)
    # Keyed by patch_hex so it matches the mapping entries above.
    voice_info: dict[str, list[str]] = {}
    for at_v_num, patch_bytes in sorted(user_patches.items()):
        patch_hex = patch_bytes.hex()
        gm_prog = at_v_to_gm.get(at_v_num, mapping.get(patch_hex, _USER_VOICE_FIRST_GM_PROGRAM))
        voice_info[patch_hex] = _format_user_patch_lines(at_v_num, patch_bytes, gm_prog)
    if voice_info:
        out["_voice_info"] = voice_info

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# MIDI helpers
# ---------------------------------------------------------------------------

def _clamp_midi_note(note: int) -> int:
    return max(0, min(127, int(note)))


def _clamp_velocity(vel: int) -> int:
    return max(0, min(127, int(vel)))


def _opll_vol_to_velocity(vol_opll: int) -> int:
    return _clamp_velocity(int(round((15 - max(0, min(15, int(vol_opll)))) * 127 / 15)))

def _opll_vol_to_cc11(vol_opll: int) -> int:
    # OPLL VOL 0〜15 → CC11 0〜127
    return max(0, min(127, 127 - (vol_opll * 8)))

def _vgm_tick_to_midi_tick(vgm_tick: int, bpm: int, ppq: int) -> int:
    return int(round(int(vgm_tick) * int(bpm) * int(ppq) / 3600.0))


def _encode_vlq(value: int) -> bytes:
    value = int(value)
    if value < 0:
        raise ValueError("VLQ value must be non-negative")
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.reverse()
    return bytes(out)


def _tempo_meta_event(bpm: int) -> bytes:
    us_per_qn = int(round(60_000_000 / max(1, int(bpm))))
    return b"\xFF\x51\x03" + struct.pack(">I", us_per_qn)[1:]


def _track_name_meta_event(name: str) -> bytes:
    name_bytes = (name or "vgm2midi").encode("utf-8", errors="replace")
    if len(name_bytes) > 127:
        name_bytes = name_bytes[:127]
    return b"\xFF\x03" + bytes([len(name_bytes)]) + name_bytes


class MidiBuilder:
    def __init__(self, ppq: int = DEFAULT_PPQ):
        self.ppq = int(ppq)
        self._events: list[MidiEvent] = []

    def add_event(self, tick: int, data: bytes, order: int = 100) -> None:
        self._events.append(MidiEvent(max(0, int(tick)), int(order), bytes(data)))

    def build(self) -> bytes:
        self._events.sort(key=lambda e: (e.tick, e.order))
        track_data = bytearray()
        prev_tick = 0
        for ev in self._events:
            delta = ev.tick - prev_tick
            track_data.extend(_encode_vlq(delta))
            track_data.extend(ev.data)
            prev_tick = ev.tick
        track_data.extend(b"\x00\xFF\x2F\x00")

        mthd = b"MThd" + struct.pack(">IHHH", 6, 0, 1, self.ppq)
        mtrk = b"MTrk" + struct.pack(">I", len(track_data)) + bytes(track_data)
        return mthd + mtrk


def _segment_to_midi_note(seg) -> int | None:
    octave, scale = _opll_note(getattr(seg, "fnum", 0), getattr(seg, "block", 0))
    if scale == "r":
        return None
    semitone = SCALE_TO_SEMITONE.get(scale)
    if semitone is None:
        return None
    return _clamp_midi_note((int(octave) + 1) * 12 + semitone)


def _at_token_to_user_v_num(at_token: str) -> int | None:
    """Parse ``'@v15'`` -> ``15``.  Returns None for preset tokens like ``'@5'``."""
    if at_token and at_token.startswith("@v"):
        try:
            return int(at_token[2:])
        except ValueError:
            pass
    return None

def compute_cc11(seg: _Segment) -> int:
    """
    CC11 は OPLL vol に忠実にマッピングする。
    強弱表現は Velocity 側で行うため、補正は一切しない。
    """
    return int((seg.vol / 15.0) * 127)
