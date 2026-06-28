# py/tx802.py
import os
import json
import random

from dataclasses import dataclass
from typing import Dict

from .opll import (
    NUM_CH,
    RHYTHM_CH_MAP,
    RHYTHM_VOICE_ID_MAP,
    _ym2413_patch_to_mgsdrv
)

from .segment_utils import (
    compute_velocity,
    compute_portamento_time
)

from .midi_utils import (
    normalize_scale,
    map_gm_drum,
    map_rx21_drum,
    DEFAULT_PPQ,
    MidiBuilder,
    _is_zero_patch,
    _tempo_meta_event,
    _track_name_meta_event,
    _vgm_tick_to_midi_tick,
    _opll_vol_to_velocity,
    _at_token_to_user_v_num,
    _segment_to_midi_note,
    compute_cc11,
)

from .opl3_op2_extractor import (
    Opl3Features2Op
)

from .tx802_presets import (
    TX802_VOCES_AB
)

# ============================================================
# TX802 Voice Mapping
# ============================================================

@dataclass(frozen=True)
class Tx802Voice:
    bank: str
    voice: int  # 11..88 など（TX802 表示番号）

    def to_vnum(self) -> int:
        """
        TX802 の「内部ボイス番号」（0–127）に変換する。
        A/B/I/C バンクを DX7II 互換の 0–127 空間にマップする想定。
        """
        v = self.voice - 1
        b = self.bank.upper()
        if b == "I":
            return 0 + v      # Internal 1–32
        if b == "C":
            return 64 + v     # Internal 33–64 or Cartridge などの想定
        if b == "A":
            return 128 + v    # Preset A
        if b == "B":
            return 192 + v    # Preset B
        return v


# ============================================================
# Default TX802 Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> A19 Violins,A11 Strings,A13 NewOrchest
#   2: OPLL Guitar          -> A35 KnockRoad,A36 RubbaRoad,A37 HardRoads
#   3: OPLL Piano           -> A33 Piano   1,A34 Piano   2,A32 PianoBrite
#   4: OPLL Flute           -> A23 Flute,A24 SongFlute,A27 Piccolo
#   5: OPLL Clarinet        -> A21 Clarinet,B40 ClariSolo,A20 Bassoon
#   6: OPLL Oboe            -> A22 Oboe,A20 Bassoon,A26 PanFloot
#   7: OPLL Trumpet         -> A7 Trumpet A,A8 SilvaTrmpt,A9 Trumpet B
#   8: OPLL Organ           -> A48 TouchOrga,A51 BriteOrga,A54 PipeOrgan
#   9: OPLL Horn            -> A1 MellowHorn,A10 FrenchHorn,A4 Tuba
#   10: OPLL Synthesizer    -> A38 FullTines,A39 ClaviStuf,A40 Clavi
#   11: OPLL Harpsichord    -> A41 Clavecin,A42 ClaviPluc,A44 HarpsiBox
#   12: OPLL Vibraphone     -> B21 VibraPhone,B18 DX Marimba,B19 Nu Marimba
#   13: OPLL Synth. Bass    -> B1 SuperBass,B2 StringBass,B3 SkweekBass
#   14: OPLL Acoust.Bass    -> B2 StringBass,B4 SmoohBass,B5 BopBass
#   15: OPLL ElectricGuitar -> B9 GuitarBox,B10 PickGuitar,B11 FingaPicka
#   16: OPLL BD1            -> B23 Swissnare,B24 Tom C4,B25 CongaDrum
#   17: OPLL SD1            -> B23 Swissnare,B24 Tom C4,B25 CongaDrum
#   18: OPLL TOM1           -> B24 Tom C4,B25 CongaDrum,B26 Tub Bells
#   19: OPLL CLOSED HH      -> B29 Claves,B30 Bells,B31 SteelCans
#   20: OPLL CYM            -> B27 Gong,B28 Timpani,B29 Claves
TX802_MELODY_OPLL_TO_DEFAULT = {
    1:  Tx802Voice("A", 11), # A11 Strings
    2:  Tx802Voice("A", 36), # A36 RubbaRoad -
    3:  Tx802Voice("A", 33), # A33 Piano   1
    4:  Tx802Voice("A", 23), # A23 Flute     -
    5:  Tx802Voice("B", 40), # B40 ClariSolo -
    6:  Tx802Voice("A", 20), # A20 Bassoon  -
    7:  Tx802Voice("A", 8),  # A8 SilvaTrmpt -
    8:  Tx802Voice("A", 48), # A48 TouchOrga
    9:  Tx802Voice("A", 10), # A10 FrenchHorn
    10: Tx802Voice("A", 38), # A38 FullTines -
    11: Tx802Voice("A", 41), # A41 Clavecin -
    12: Tx802Voice("B", 21), # B21 VibraPhone -
    13: Tx802Voice("B", 3), # B3 SkweekBass
    14: Tx802Voice("B", 2), # B2 StringBass -
    15: Tx802Voice("B", 11), # ,B11 FingaPicka
}

# ============================================================
# OPLL → TX802 Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> A19 Violins
#   2: OPLL Guitar          -> B10 PickGuitar
#   3: OPLL Piano           -> A33 Piano   1
#   4: OPLL Flute           -> A23 Flute
#   5: OPLL Clarinet        -> A21 Clarinet
#   6: OPLL Oboe            -> A22 Oboe
#   7: OPLL Trumpet         -> A07 Trumpet  A
#   8: OPLL Organ           -> A51 BriteOrgan
#   9: OPLL Horn            -> A10 FrenchHorn
#   10: OPLL Synth          -> B43 WhapSynth
#   11: OPLL Harpsichord    -> A44 HarpsiBox
#   12: OPLL Vibraphone     -> B21 VibraPhone
#   13: OPLL SynthBass      -> B48 HarmoSynth
#   14: OPLL AcousticBass   -> A16 BowedBass
#   15: OPLL ElectricGuitar -> B09 GuitarBox

TX802_MELODY_OPLL_TO_OPLL = {
    1:  Tx802Voice("A", 19), # A19 Violins
    2:  Tx802Voice("B", 10), # B10 PickGuitar
    3:  Tx802Voice("A", 23), # A23 Flute
    4:  Tx802Voice("A", 21), # A21 Clarinet
    5:  Tx802Voice("A", 22), # A22 Oboe
    6:  Tx802Voice("A", 7),  # A07 Trumpet  A
    7:  Tx802Voice("A", 21), # A21 Clarinet
    8:  Tx802Voice("A", 51), # A51 BriteOrgan
    9:  Tx802Voice("A", 10), # A10 FrenchHorn
    10: Tx802Voice("B", 43), # B43 WhapSynth
    11: Tx802Voice("A", 44), # A44 HarpsiBox
    12: Tx802Voice("B", 21), # B21 VibraPhone
    13: Tx802Voice("B", 48), # B48 HarmoSynth
    14: Tx802Voice("A", 16), # A16 BowedBass
    15: Tx802Voice("B", 9),  # B09 GuitarBox
}

# ============================================================
# GM → TX802 Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> GM 0  Piano       -> A33 Piano   1
#   2: OPLL Guitar          -> GM 6  Harpsi      -> A45 HarpsiWire
#   3: OPLL Piano           -> GM 11 Vibes       -> B21 VibraPhone
#   4: OPLL Flute           -> GM 19 Church Org  -> A51 BriteOrgan
#   5: OPLL Clarinet        -> GM 25 Ac.Gt       -> B09 GuitarBox
#   6: OPLL Oboe            -> GM 27 E.Gt        -> B10 PickGuitar
#   7: OPLL Trumpet         -> GM 32 AcBass      -> B03 SkweekBass
#   8: OPLL Organ           -> GM 38 SynBass     -> B07 JazzBass
#   9: OPLL Horn            -> GM 40 Violin      -> A19 Violins
#   10: OPLL Synth          -> GM 56 Trumpet     -> A07 Trumpet  A
#   11: OPLL Harpsichord    -> GM 60 Brass       -> B42 ClaviBrass
#   12: OPLL Vibraphone     -> GM 68 Oboe        -> A22 Oboe
#   13: OPLL SynthBass      -> GM 71 Clarinet    -> A21 Clarinet
#   14: OPLL AcousticBass   -> GM 73 Flute       -> A23 Flute
#   15: OPLL ElectricGuitar -> GM 81 Lead1       -> B12 LeadaPicka

TX802_MELODY_OPLL_TO_GM = {
    1:  Tx802Voice("A", 33), # A33 Piano   1
    2:  Tx802Voice("A", 45), # A45 HarpsiWire
    3:  Tx802Voice("B", 21), # B21 VibraPhone
    4:  Tx802Voice("A", 51), # A51 BriteOrgan
    5:  Tx802Voice("B", 9),  # B09 GuitarBox
    6:  Tx802Voice("B", 10), # B10 PickGuitar
    7:  Tx802Voice("B", 3),  # B03 SkweekBass
    8:  Tx802Voice("B", 7),  # B07 JazzBass
    9:  Tx802Voice("A", 19), # A19 Violins
    10: Tx802Voice("A", 7),  # A07 Trumpet  A
    11: Tx802Voice("B", 42), # B42 ClaviBrass
    12: Tx802Voice("A", 22), # A22 Oboe
    13: Tx802Voice("A", 21), # A21 Clarinet
    14: Tx802Voice("A", 23), # A23 Flute
    15: Tx802Voice("B", 12), # B12 LeadaPicka
}


# ============================================================
# Custom1 TX802 Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> A31 EbonyIvory
#   2: OPLL Guitar          -> A34 Piano 2 
#   3: OPLL Piano           -> A11 Strings
#   4: OPLL Flute           -> B14 12 Strings
#   5: OPLL Clarinet        -> B07 JazzBass
#   6: OPLL Oboe            -> B16 Shami
#   7: OPLL Trumpet         -> B15 Classipika
#   8: OPLL Organ           -> A12 HallOrch
#   9: OPLL Horn            -> A10 FrenchHorn
#   10: OPLL Synth          -> A15 LiveStrg 
#   11: OPLL Harpsichord    -> A45 HarpsWire
#   12: OPLL Vibraphone     -> A12 HallOrch
#   13: OPLL SynthBass      -> B11 FingaPicka
#   14: OPLL AcousticBass   -> B12 LeadaPicka
#   15: OPLL ElectricGuitar -> A14 Analog-Str

TX802_MELODY_OPLL_TO_CUSTOM1 = {
    1:  Tx802Voice("A", 31), # A31 EbonyIvory
    2:  Tx802Voice("A", 34), # A34 Piano 2 
    3:  Tx802Voice("A", 11), # A11 Strings
    4:  Tx802Voice("B", 14), # B14 12 Strings
    5:  Tx802Voice("B", 7),  # B07 JazzBass
    6:  Tx802Voice("B", 16), # B16 Shami
    7:  Tx802Voice("B", 15), # B15 Classipika
    8:  Tx802Voice("A", 12), # A12 HallOrch
    9:  Tx802Voice("A", 10), # A10 FrenchHorn
    10: Tx802Voice("A", 15), # A15 LiveStrg -
    11: Tx802Voice("A", 45), # A45 HarpsWire -
    12: Tx802Voice("A", 12), # A12 HallOrch
    13: Tx802Voice("B", 11), # B11 FingaPicka
    14: Tx802Voice("B", 12), # B12 LeadaPicka
    15: Tx802Voice("A", 14), # A14 Analog-Str - 
}

# ユーザ音色を割り当てる TX802 プログラム番号の開始位置（0-indexed）
_USER_VOICE_FIRST_TX802_PROGRAM = 20
# 「未使用」扱いにする TX802 プログラム番号（0-indexed）
_TX802_PROGRAM_UNUSED = 127

def tx802_bank_voice_to_vnum(bank: str, voice: int) -> int:
    bank = bank.upper()
    if bank == "I":
        base = 0
    elif bank == "B":
        base = 32
    elif bank == "C":
        base = 64
    elif bank == "A":
        base = 96
    else:
        raise ValueError(f"Unknown TX802 bank: {bank}")

    return base + (voice - 1)

def classify_opl3_to_tx802(feat: Opl3Features2Op) -> Tx802Voice:
    """
    OPL3 2OP 特徴量から、最も近いと思われる TX802 プリセットを推定する。
    - EP / Bell
    - Brass
    - Lead
    - Reed / Wind
    - Bass
    - Strings / Pad
    くらいの大分類でざっくり振り分ける。
    """

    m = feat.mod
    c = feat.car
    fb = feat.fb
    alg = feat.alg

    # ざっくり特徴
    fast_attack = c.ar >= 12 or m.ar >= 12
    slow_attack = c.ar <= 5 and m.ar <= 5
    long_sustain = feat.long_sustain
    percussive = feat.percussive
    bright = feat.bright
    strong_fb = feat.strong_fb
    weak_fb = feat.weak_fb
    vib_used = (m.vib == 1) or (c.vib == 1)

    # 倍音の粗さ
    high_mul = (m.mul >= 4) or (c.mul >= 4)
    low_mul = (m.mul <= 2) and (c.mul <= 2)

    # キャリアの音量感（TL 小さいほど大きい）
    car_loud = c.tl <= 24
    car_soft = c.tl >= 32

    # --------------------------------------------------------
    # 1. EP / Bell 系
    # --------------------------------------------------------
    # ・FB 弱い
    # ・アタック速い
    # ・明るい
    # ・サスティンは短め〜中庸
    if weak_fb and fast_attack and bright and not long_sustain:
        # A11: E.PIANO 1 に寄せる
        return Tx802Voice("A", 11)

    # より Bell / Hard EP 寄り
    if weak_fb and fast_attack and high_mul and bright:
        # A12: E.PIANO 2 / Bell 系
        return Tx802Voice("A", 12)

    # --------------------------------------------------------
    # 2. Brass 系
    # --------------------------------------------------------
    # ・アタック速い
    # ・FB 中程度以上
    # ・MUL 低〜中
    if fast_attack and fb >= 2 and fb <= 5 and low_mul and not percussive:
        # A21: BRASS 1
        return Tx802Voice("A", 21)

    # シンセ寄りブラス
    if fast_attack and fb >= 3 and bright and not percussive:
        # A22: SYN-BRASS
        return Tx802Voice("A", 22)

    # --------------------------------------------------------
    # 3. Lead 系
    # --------------------------------------------------------
    # ・FB 強め
    # ・MUL 高め
    # ・サスティン長め or 中庸
    if strong_fb and high_mul and not percussive:
        # A23: SYN-LEAD 1
        return Tx802Voice("A", 23)

    # 細めのリード
    if strong_fb and bright and not long_sustain:
        # A24: SYN-LEAD 2
        return Tx802Voice("A", 24)

    # --------------------------------------------------------
    # 4. Reed / Wind 系
    # --------------------------------------------------------
    # ・VIB 使用
    # ・MUL 低め
    # ・FB 弱め
    if vib_used and low_mul and fb <= 3 and not percussive:
        # B14: REED / WIND 系
        return Tx802Voice("B", 14)

    # --------------------------------------------------------
    # 5. Bass 系
    # --------------------------------------------------------
    # ・TL 深い（小さくない）
    # ・MUL 低め
    # ・アタック中〜速め
    if car_soft and low_mul and not slow_attack:
        # B11: BASS 1
        return Tx802Voice("B", 11)

    # シンセベース寄り
    if car_soft and high_mul and strong_fb:
        # B12: SYN-BASS
        return Tx802Voice("B", 12)

    # --------------------------------------------------------
    # 6. Strings / Pad 系
    # --------------------------------------------------------
    # ・アタック遅め
    # ・サスティン長い
    if slow_attack and long_sustain and not strong_fb:
        # A31: STRINGS
        return Tx802Voice("A", 31)

    # Pad 系（少し FB あり）
    if long_sustain and fb >= 2 and not bright:
        # B21: PAD 系
        return Tx802Voice("B", 21)

    # --------------------------------------------------------
    # 7. Percussive / Pluck 系
    # --------------------------------------------------------
    # ・アタック速い
    # ・サスティン短い
    if percussive and fast_attack and not long_sustain:
        # A13 あたりでもいいが、ここでは汎用 EP/PLUCK として A11 に逃がす
        return Tx802Voice("A", 11)

    # --------------------------------------------------------
    # 8. Fallback
    # --------------------------------------------------------
    # どう分類しても微妙な場合は汎用リードに逃がす
    return Tx802Voice("A", 23)

def auto_classify_user_patch_tx802(patch_bytes: bytes) -> Tx802Voice:
    """
    YM2413 パッチを TX802 の最適プリセットに自動分類する。
    - OPLL → MGSDRV 形式に変換したパラメータを元に
    - 音色の「傾向」から TX802 プリセットを推定する
    """

    d = _ym2413_patch_to_mgsdrv(patch_bytes)
    tl, fb = d["tl"], d["fb"]
    m = d["mod"]
    c = d["car"]

    # modulator
    m_ar = m[0]
    m_dr = m[1]
    m_sl = m[2]
    m_rr = m[3]
    m_ks = m[4]
    m_mul = m[5]
    m_eg = m[6]
    m_vib = m[7]

    # carrier
    c_ar = c[0]
    c_dr = c[1]
    c_sl = c[2]
    c_rr = c[3]
    c_ks = c[4]
    c_mul = c[5]
    c_eg = c[6]
    c_vib = c[7]


    # ざっくり特徴量
    fast_attack = c_ar >= 12 or m_ar >= 12
    slow_attack = c_ar <= 5 and m_ar <= 5
    long_sustain = c_sl >= 8 or m_sl >= 8
    short_sustain = c_sl <= 3 and m_sl <= 3
    bright = tl <= 16 and (m_mul >= 3 or c_mul >= 3)
    dark = tl >= 24 and m_mul <= 2 and c_mul <= 2
    strong_fb = fb >= 4
    weak_fb = fb == 0
    vib_used = (m_vib == 1) or (c_vib == 1)

    # ─────────────────────────────────────
    # 1. EP / Bell 系
    # ─────────────────────────────────────
    # ・FB=0
    # ・アタック速い
    # ・サスティン短め or 中庸
    if weak_fb and fast_attack and not long_sustain and bright:
        # A11: E.PIANO 1
        return Tx802Voice("A", 11)

    # Bell 系（より硬い・高倍音）
    if weak_fb and fast_attack and bright and (m_mul >= 4 or c_mul >= 4):
        # A12: E.PIANO 2 / Bell 系に寄せる
        return Tx802Voice("A", 12)

    # ─────────────────────────────────────
    # 2. Brass 系
    # ─────────────────────────────────────
    # ・アタック速い
    # ・FB 中程度以上
    # ・MUL 低〜中
    if fast_attack and fb >= 2 and fb <= 5 and c_mul <= 4 and not short_sustain:
        # A21: BRASS 1
        return Tx802Voice("A", 21)

    # よりシンセ寄りブラス
    if fast_attack and strong_fb and bright:
        # A22: BRASS 2 / SYN-BRASS 系
        return Tx802Voice("A", 22)

    # ─────────────────────────────────────
    # 3. Lead 系
    # ─────────────────────────────────────
    # ・FB 強め
    # ・MUL 高め
    # ・サスティン長め or 中庸
    if strong_fb and (m_mul >= 4 or c_mul >= 4) and not short_sustain:
        # A23: SYN-LEAD 1
        return Tx802Voice("A", 23)

    # より細いリード
    if strong_fb and bright and short_sustain:
        # A24: SYN-LEAD 2
        return Tx802Voice("A", 24)

    # ─────────────────────────────────────
    # 4. Reed / Wind 系
    # ─────────────────────────────────────
    # ・VIB 使用
    # ・MUL 低め
    # ・FB 弱め
    if vib_used and m_mul <= 3 and c_mul <= 3 and fb <= 3:
        # B14: REED
        return Tx802Voice("B", 14)

    # ─────────────────────────────────────
    # 5. Bass 系
    # ─────────────────────────────────────
    # ・TL 深い
    # ・MUL 低め
    # ・アタック中〜速め
    if tl >= 20 and m_mul <= 3 and c_mul <= 3 and not slow_attack:
        # B11: BASS 1
        return Tx802Voice("B", 11)

    # よりシンセ寄りベース
    if tl >= 20 and (m_mul >= 3 or c_mul >= 3) and strong_fb:
        # B12: SYN-BASS
        return Tx802Voice("B", 12)

    # ─────────────────────────────────────
    # 6. Strings / Pad 系
    # ─────────────────────────────────────
    # ・アタック遅め
    # ・サスティン長い
    if slow_attack and long_sustain and not strong_fb:
        # A31: STRINGS
        return Tx802Voice("A", 31)

    # Pad 系（少し FB 強め）
    if long_sustain and fb >= 2 and not bright:
        # B21: PAD 系
        return Tx802Voice("B", 21)

    # ─────────────────────────────────────
    # 7. Fallback
    # ─────────────────────────────────────
    # どう分類しても微妙な場合は汎用リードに逃がす
    return Tx802Voice("A", 23)

def _distance_opll_to_tx802(mgs, txv):
    """
    MGSDRV パラメータと TX802 プリセットの距離を計算する。
    txv は TX802_VOCES_AB の 1 要素（dict）
    """

    # MGSDRV
    tl = mgs["tl"]
    fb = mgs["fb"]
    m = mgs["mod"]
    c = mgs["car"]

    # TX802
    def g(key, default=0):
        return int(txv.get(key, default))

    # 距離計算（L1 ノルム）
    dist = 0

    # FB
    dist += abs(fb - g("FB"))

    # TL → キャリア TL に寄せる
    dist += abs(tl - g("OP2_TL"))

    # Modulator
    dist += abs(m[0] - g("OP1_AR"))
    dist += abs(m[1] - g("OP1_DR"))
    dist += abs(m[2] - g("OP1_SL"))
    dist += abs(m[3] - g("OP1_RR"))
    dist += abs(m[4] - g("OP1_KSL"))
    dist += abs(m[5] - g("OP1_MULTI"))
    dist += abs(m[6] - g("OP1_AM"))
    dist += abs(m[7] - g("OP1_VIB"))

    # Carrier
    dist += abs(c[0] - g("OP2_AR"))
    dist += abs(c[1] - g("OP2_DR"))
    dist += abs(c[2] - g("OP2_SL"))
    dist += abs(c[3] - g("OP2_RR"))
    dist += abs(c[4] - g("OP2_KSL"))
    dist += abs(c[5] - g("OP2_MULTI"))
    dist += abs(c[6] - g("OP2_AM"))
    dist += abs(c[7] - g("OP2_VIB"))

    return dist


def classify_user_patch_by_distance_tx802(patch_bytes: bytes) -> Tx802Voice:
    """
    OPLL パッチを TX802 プリセットの中から
    距離計算で最も近いものを返す。
    """

    mgs = _ym2413_patch_to_mgsdrv(patch_bytes)

    best = None
    best_dist = 999999

    for txv in TX802_VOCES_AB:
        dist = _distance_opll_to_tx802(mgs, txv)
        if dist < best_dist:
            best_dist = dist
            best = txv

    if best is None:
        return Tx802Voice("A", 23)

    return Tx802Voice(best["bank"], best["voice"])

def _build_user_voice_tx802_map(
    user_patches: dict[int, bytes],
    existing_map: dict[str, dict],
) -> tuple[dict[int, dict], dict[str, dict]]:

    at_v_to_tx802: dict[int, dict] = {}
    updated = dict(existing_map)

    for at_v_num, patch_bytes in user_patches.items():
        patch_hex = patch_bytes.hex()

        # 1. all-zero → I1 固定
        if _is_zero_patch(patch_bytes):
            entry = {
                "bank": "I",
                "voice": 1,
                "label": "Unused (all-zero)",
            }
            at_v_to_tx802[at_v_num] = entry
            updated[patch_hex] = entry
            continue

        # 2. 既存マップがあればそれを優先
        if patch_hex in updated:
            entry = updated[patch_hex]
            at_v_to_tx802[at_v_num] = entry
            continue

        # 3. 新規パッチ → Presets A/Bに対してパラメータの自動計算を行い初期値を算出
        # txv = auto_classify_user_patch_tx802(patch_bytes)
        txv = classify_user_patch_by_distance_tx802(patch_bytes)

        entry = {
            "bank": txv.bank,
            "voice": txv.voice,
            "label": f"{txv.bank}{txv.voice}",
        }

        at_v_to_tx802[at_v_num] = entry
        updated[patch_hex] = entry

    return at_v_to_tx802, updated

def _reverse_lookup_tx802_voice(vnum: int) -> Tx802Voice | None:
    """
    内部 vnum (0–127) から Tx802Voice(bank, voice) を推定する。
    to_vnum() の逆写像として使う補助関数。
    実機のバンク構成に合わせて必要なら調整。
    """
    # I バンク
    if 0 <= vnum < 32:
        return Tx802Voice("I", vnum + 1)
    # C バンク
    if 64 <= vnum < 96:
        return Tx802Voice("C", (vnum - 64) + 1)
    # A バンク（to_vnum では 128+v を返しているので、そのままでは戻せない。
    # 実際には vnum & 0x7F などでマスクされる前提なら、ここは環境に合わせて調整が必要）
    # B バンクも同様。ここでは None を返すフォールバックにしておく。
    return None

def _format_user_patch_lines_tx802(
    at_v_num: int,
    patch_bytes: bytes,
    tx802_prog: dict,
    tx802_voice: dict,
    vnum: int,
):
    lines = []

    lines.append(
        f"User patch v{at_v_num}: TX802 {tx802_prog['bank']}{tx802_prog['voice']} (vnum={vnum})"
    )

    regs = patch_bytes.hex().upper()
    lines.append(f"Inst {vnum}: regs = {' '.join(regs[i:i+2] for i in range(0, 16, 2))}")

    # MGSDRV 形式のパラメータを表示
    d = _ym2413_patch_to_mgsdrv(patch_bytes)
    tl, fb = d["tl"], d["fb"]
    m = d["mod"]
    c = d["car"]

    lines.append(f"\tTL={tl} FB={fb}")
    lines.append(
        f"\tMO: AR={m[0]:2} DR={m[1]:2} SL={m[2]:2} RR={m[3]:2} KL={m[4]} MT={m[5]} AM={m[6]} VB={m[7]} EG={m[6]} KR={m[4]} DT=0"
    )
    lines.append(
        f"\tCA: AR={c[0]:2} DR={c[1]:2} SL={c[2]:2} RR={c[3]:2} KL={c[4]} MT={c[5]} AM={c[6]} VB={c[7]} EG={c[6]} KR={c[4]} DT=0"
    )

    return lines

def _user_voice_tx802_map_path(output_dir: str, base_name: str) -> str:
    return os.path.join(output_dir, f"{base_name}.user_voice_tx802.json")

def _save_user_voice_tx802_map(path: str, updated_map: dict[str, dict]):
    """
    Save TX802 user voice map JSON.
    JSON には bank / voice / label のみ保存し、
    vnum は保存しない（Python 側で自動計算する）。
    """

    out = {}
    voice_info = {}

    for patch_hex, entry in updated_map.items():
        bank = entry["bank"]
        voice = entry["voice"]
        label = entry.get("label", "")

        # JSON に保存するのは bank / voice / label のみ
        out[patch_hex] = {
            "bank": bank,
            "voice": voice,
            "label": label
        }

        # コメント用に vnum を計算
        vnum = tx802_bank_voice_to_vnum(bank, voice)

        voice_info[patch_hex] = [
            f"TX802 {bank}{voice} (vnum={vnum})",
            f"Inst {vnum}: regs = {patch_hex}"
        ]

    out["_voice_info"] = voice_info

    with open(path, "w") as f:
        json.dump(out, f, indent=2)

def _load_user_voice_tx802_map(path: str) -> dict[str, dict]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        result = {}
        for k, v in data.items():
            if k.startswith("_"):
                continue
            if isinstance(k, str) and isinstance(v, dict):
                result[k.lower()] = v
        return result
    except Exception:
        return {}

def save_tx802_voice_syx(path: str, syx_bytes: bytes):
    with open(path, "wb") as f:
        f.write(syx_bytes)

def build_tx802_voice_sysex(txv_params: dict, name: str = "OPLL"):
    """
    txv_params: {
        "op1": { "ar":.., "dr":.., "sl":.., "rr":.., "tl":.., "rs":.., "dt":.., "mul":.., "am":.. },
        "op2": { ... },
        "fb": int,
        "alg": int
    }
    """

    def op_block(op):
        # TX802 operator block (17 bytes)
        return [
            op["ar"], op["dr"], op["sl"], op["rr"],
            op["tl"], op["rs"], op["dt"], op["mul"],
            op["am"], 0, 0, 0, 0, 0, 0, 0, 0
        ]

    # OP1, OP2 は OPLL から生成
    op1 = op_block(txv_params["op1"])
    op2 = op_block(txv_params["op2"])

    # OP3, OP4 はデフォルト（無音）
    op3 = [0]*17
    op4 = [0]*17

    # Pitch EG（デフォルト）
    peg = [0, 0, 0, 0]

    # Algorithm / Feedback
    alg = txv_params.get("alg", 0)
    fb  = txv_params.get("fb", 0)

    # LFO（デフォルト）
    lfo = [0, 0, 0, 0, 0]

    # Name（10 bytes）
    name_bytes = [ord(c) & 0x7F for c in name[:10]]
    name_bytes += [32] * (10 - len(name_bytes))

    # 残りは 86 bytes の 0x00
    tail = [0] * 86

    # 155 bytes voice data
    voice_data = (
        op1 + op2 + op3 + op4 +
        peg +
        [alg, fb] +
        lfo +
        name_bytes +
        tail
    )

    # SysEx header
    syx = [0xF0, 0x43, 0x00, 0x09, 0x20, 0x00]
    syx += voice_data
    syx.append(0xF7)

    return bytes(syx)

def get_tx802_melody_voice(opll_patch: int, melody_mode: str = "mb") -> Tx802Voice:
    tables = {
        "default": TX802_MELODY_OPLL_TO_DEFAULT,
        "gm": TX802_MELODY_OPLL_TO_GM,
        "opll": TX802_MELODY_OPLL_TO_OPLL,
    }

    # melody_mode の typo に強い
    table = tables.get(melody_mode, TX802_MELODY_OPLL_TO_DEFAULT)

    # opll_patch が範囲外でも安全
    # fallback は GM の 0 番（= Lead1 Square 相当）
    return table.get(opll_patch, table.get(0, Tx802Voice("A", 23)))

def compute_portamento_time_tx802(prev_note, next_note, tick_length, bpm):
    # 音程差（半音）
    diff = abs(next_note - prev_note)

    # ノート長（秒）
    sec = tick_length * (60.0 / (bpm * ppq))

    # TX802 の CC5 は指数カーブなので補正
    # diff=12（1oct）で CC5=25〜35 が自然
    base = diff * 2.2

    # ノート長が短い場合は短縮
    if sec < 0.2:
        base *= 0.6
    elif sec > 0.5:
        base *= 1.3

    # CC5 の範囲に収める
    return int(max(1, min(63, base)))

VELOCITY_SENS_TABLE = {
    "piano": 1.00,
    "epiano": 0.90,
    "clav": 0.85,
    "brass": 0.70,
    "strings": 0.60,
    "pad": 0.40,
    "bass": 0.75,
    "lead": 0.80,
}

def compute_velocity_tx802(seg, txv, is_portamento=False):
    opll_vol = getattr(seg, "vol", 15)

    # --- 基本レンジ設定 ---
    base_min = 55
    base_max = 127
    steps = 15  # OPLL vol=1〜15

    # 線形マッピング（1ステップ ≈ 4〜5）
    v = base_min + int((base_max - base_min) * (opll_vol - 1) / (steps - 1))

    # --- 微調整：指数カーブを少しだけ混ぜる ---
    # 低音量をほんの少しだけ持ち上げる（過剰にしない）
    if opll_vol <= 3:
        v += 8
    elif opll_vol <= 6:
        v += 4

    # --- 揺らぎ（±2以内） ---
    v += random.randint(-2, 2)

    # --- ポルタメント補正 ---
    if is_portamento:
        v = int(v * 0.90)

    return max(1, min(127, v))


def tx802_append_init_events(builder, time0=0):
    """
    Domino TX802 初期化シーケンスを MidiBuilder に追加する。
    builder: MidiBuilder インスタンス
    time0: すべてのイベントを置く tick（通常 0）
    """

    def add_sysex(data, order=0):
        builder.add_event(time0, bytes(data), order=order)

    def add_cc(ch, cc, val, order=0):
        builder.add_event(time0, bytes([0xB0 | ch, cc, val]), order=order)

    def add_cp(ch, val, order=0):
        builder.add_event(time0, bytes([0xD0 | ch, val]), order=order)

    def add_pb(ch, val14, order=0):
        lo = val14 & 0x7F
        hi = (val14 >> 7) & 0x7F
        builder.add_event(time0, bytes([0xE0 | ch, lo, hi]), order=order)

    channels = range(8)

    # --- TG1〜TG8 Voice Number 初期化 ---
    sysex1 = [
        [0xF0,0x43,0x10,0x1A,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x08,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x01,0x01,0xF7],
        [0xF0,0x43,0x10,0x1A,0x09,0x01,0xF7],
        [0xF0,0x43,0x10,0x1A,0x02,0x02,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0A,0x02,0xF7],
        [0xF0,0x43,0x10,0x1A,0x03,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0B,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x04,0x04,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0C,0x04,0xF7],
        [0xF0,0x43,0x10,0x1A,0x05,0x05,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0D,0x05,0xF7],
        [0xF0,0x43,0x10,0x1A,0x06,0x06,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0E,0x06,0xF7],
        [0xF0,0x43,0x10,0x1A,0x07,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x0F,0x07,0xF7],
    ]
    for s in sysex1:
        add_sysex(s, order=1)

    # --- CC 初期化 ---
    for ch in channels:
        add_cc(ch, 1, 0,   order=2)   # Mod
        add_cc(ch, 2, 127, order=2)   # Breath
        add_cc(ch, 4, 127, order=2)   # Foot
        add_cc(ch, 5, 0,   order=2)   # Porta Time
        add_cc(ch, 0x40, 0, order=2)  # Sustain
        add_cc(ch, 0x41, 0, order=2)  # Porta Sw
        add_cp(ch, 0,      order=2)   # Aftertouch
        add_pb(ch, 0x2000, order=2)   # PB center

    # --- TG Note Shift / Output Assign ---
    sysex2 = [
        [0xF0,0x43,0x10,0x1A,0x10,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x11,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x12,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x13,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x14,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x15,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x16,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x17,0x00,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x48,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x49,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4A,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4B,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4C,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4D,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4E,0x00,0xF7],
        [0xF0,0x43,0x10,0x1A,0x4F,0x00,0xF7],
    ]
    for s in sysex2:
        add_sysex(s, order=3)

    # --- Volume ---
    for ch in channels:
        add_cc(ch, 7, 127, order=4)

    # --- EG Forced Damp / PB Range / Detune ---
    sysex3 = [
        [0xF0,0x43,0x10,0x1A,0x28,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x29,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2A,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2B,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2C,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2D,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2E,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x2F,0x03,0xF7],
        [0xF0,0x43,0x10,0x1A,0x40,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x41,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x42,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x43,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x44,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x45,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x46,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x47,0x18,0xF7],
        [0xF0,0x43,0x10,0x1A,0x18,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x19,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1A,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1B,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1C,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1D,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1E,0x07,0xF7],
        [0xF0,0x43,0x10,0x1A,0x1F,0x07,0xF7],
    ]
    for s in sysex3:
        add_sysex(s, order=5)


def midi_builder_tx802(
    segments_by_ch: dict,
    bpm: int,
    ppq: int = DEFAULT_PPQ,
    track_name: str = "vgm2midi",
    user_voice_tx802_map: dict[int, int] | None = None,
    melody_mode: str = "default",
    rhythm_mode: str = "gm"
) -> MidiBuilder:

    builder = MidiBuilder(ppq=ppq)
    builder.add_event(0, _tempo_meta_event(bpm), order=0)
    builder.add_event(0, _track_name_meta_event(track_name), order=1)

    # ------------------------------------------------------------
    # ★ TX802 初期化シーケンス
    # ------------------------------------------------------------
    #tx802_append_init_events(builder, time0=0)

    last_program_by_ch: dict[int, int] = {}
    last_bank_by_ch: dict[int, tuple[int, int]] = {}
    last_note_by_ch: dict[int, int] = {}

    rhythm_channels = set(RHYTHM_CH_MAP.values())

    # ------------------------------------------------------------
    # CH0〜CH8 を順番に処理
    # ------------------------------------------------------------
    for ch in range(NUM_CH):
        # ------------------------------------------------------------
        # ドラムチャンネル
        # ------------------------------------------------------------
        if ch in rhythm_channels:
            for seg in segments_by_ch.get(ch, []):
                if int(getattr(seg, "keyon", 0)) != 1:
                    continue

                start_tick = _vgm_tick_to_midi_tick(getattr(seg, "tick_start", 0), bpm, ppq)
                end_tick   = _vgm_tick_to_midi_tick(getattr(seg, "tick_end",   0), bpm, ppq)
                if end_tick <= start_tick:
                    continue

                drum_defs = (
                    ("bd", getattr(seg, "bd", 0)),
                    ("sd", getattr(seg, "sd", 0)),
                    ("tom", getattr(seg, "tom", 0)),
                    ("tc", getattr(seg, "tc", 0)),
                    ("hh", getattr(seg, "hh", 0)),
                    ("cym", getattr(seg, "cym", 0)),
                )

                raw_scale = getattr(seg, "scale", 0)
                scale = normalize_scale(raw_scale)

                for drum_name, is_on in drum_defs:
                    if int(is_on) != 1:
                        continue

                    if rhythm_mode == "gm":
                        drum_note = map_gm_drum(drum_name, scale)
                    elif rhythm_mode == "rx21":
                        drum_note = map_rx21_drum(drum_name, scale)
                    else:
                        drum_note = map_gm_drum(drum_name, scale)

                    vel = _opll_vol_to_velocity(getattr(seg, "vol", 15))

                    builder.add_event(start_tick, bytes([0x99, drum_note, vel]), order=30)
                    builder.add_event(end_tick,   bytes([0x89, drum_note, 0]),   order=40)

            continue

        # ------------------------------------------------------------
        # メロディ CH（TX802 TG）
        # ------------------------------------------------------------
        for seg in segments_by_ch.get(ch, []):
            if int(getattr(seg, "keyon", 0)) != 1:
                continue

            start_tick = _vgm_tick_to_midi_tick(getattr(seg, "tick_start", 0), bpm, ppq)
            end_tick   = _vgm_tick_to_midi_tick(getattr(seg, "tick_end",   0), bpm, ppq)
            if end_tick <= start_tick:
                continue

            midi_ch = ch
            inst = int(getattr(seg, "inst", 0))

            # inst==0 → user patch (@vN)
            if inst == 0:
                at_token = getattr(seg, "at_token", "") or ""
                at_v_num = _at_token_to_user_v_num(at_token)

                if user_voice_tx802_map and at_v_num is not None and at_v_num in user_voice_tx802_map:
                    entry = user_voice_tx802_map[at_v_num]
                    bank = entry["bank"]
                    voice = entry["voice"]
                    program = max(0, min(63, voice - 1))
                    txv = None
                else:
                    txv = get_tx802_melody_voice(0, melody_mode)
                    if txv is None:
                        bank = "I"
                        program = 0
                    else:
                        bank = txv.bank
                        voice = txv.voice
                        program = max(0, min(63, voice - 1))
                force_bank_select = True

            else:
                txv = get_tx802_melody_voice(inst, melody_mode)
                if txv is None:
                    bank = "I"
                    program = 0
                else:
                    bank = txv.bank
                    voice = txv.voice
                    program = max(0, min(63, voice - 1))

                force_bank_select = False

            # ------------------------------------------------------------
            # Bank Select（TX802 は必須）
            # ------------------------------------------------------------
            bank_str = (bank or "I").upper()

            if bank_str == "A":
                msb, lsb = 1, 0
            elif bank_str == "B":
                msb, lsb = 1, 1
            elif bank_str == "C":
                msb, lsb = 0, 1
            else:
                msb, lsb = 0, 0

            bank_tick = max(0, start_tick - 1)
            #if last_bank_by_ch.get(midi_ch) != (msb, lsb):
            #    builder.add_event(bank_tick, bytes([0xB0 | midi_ch, 0x00, msb]), order=8)
            #    builder.add_event(bank_tick, bytes([0xB0 | midi_ch, 0x20, lsb]), order=9)
            #    last_bank_by_ch[midi_ch] = (msb, lsb)

            # 毎回 CC0/32 を送ることで、TX802 に必ず正しいバンクを明示
            builder.add_event(bank_tick, bytes([0xB0 | midi_ch, 0x00, msb]), order=8)
            builder.add_event(bank_tick, bytes([0xB0 | midi_ch, 0x20, lsb]), order=9)

            # ----------------------------
            # Program Change
            # ----------------------------
            if last_program_by_ch.get(midi_ch) != program:
                builder.add_event(start_tick, bytes([0xC0 | midi_ch, program]), order=10)
                last_program_by_ch[midi_ch] = program

            # ------------------------------------------------------------
            # Note On / Off
            # ------------------------------------------------------------
            midi_note = _segment_to_midi_note(seg)
            if midi_note is None:
                continue

            vel = compute_velocity(seg)

            # ------------------------------------------------------------
            # ★ TX802 Portamento
            # ------------------------------------------------------------
            is_portamento = int(getattr(seg, "is_portamento", 0))
            if is_portamento == 1 and midi_ch in last_note_by_ch:
                prev_note = last_note_by_ch[midi_ch]

                # ノート長（tick）
                tick_len = end_tick - start_tick

                # TX802 専用ポルタメント時間
                port_time = compute_portamento_time_tx802(
                    prev_note, midi_note, tick_len, bpm
                )

                # TX802 は Note On より前に CC を送る必要がある
                port_tick = max(0, start_tick - 2)

                builder.add_event(port_tick, bytes([0xB0 | midi_ch, 84, prev_note]), order=15)
                builder.add_event(port_tick, bytes([0xB0 | midi_ch, 65, 127]), order=16)
                builder.add_event(port_tick, bytes([0xB0 | midi_ch, 5, port_time]), order=17)

                # Note Off 時に Portamento OFF
                builder.add_event(end_tick, bytes([0xB0 | midi_ch, 65, 0]), order=35)

            # ------------------------------------------------------------
            # CC11（Expression）
            # ------------------------------------------------------------
            cc11 = compute_cc11(seg)
            builder.add_event(start_tick, bytes([0xB0 | midi_ch, 11, cc11]), order=18)

            # ------------------------------------------------------------
            # ★ TX802 Velocity
            # ------------------------------------------------------------
            velocity = compute_velocity_tx802(seg, txv, is_portamento)
            #velocity = compute_velocity(seg)
            # Note On
            builder.add_event(
                start_tick,
                bytes([0x90 | midi_ch, midi_note, velocity]),
                order=20,
            )

            # Note Off
            builder.add_event(end_tick,   bytes([0x80 | midi_ch, midi_note, 0]), order=40)

            last_note_by_ch[midi_ch] = midi_note

    return builder
