# ============================================================
#  OPL3 2OP Feature Extractor
#  - MoonBlaster 2OP instrument table embedded
#  - Extracts operator parameters + derived features
# ============================================================

from dataclasses import dataclass


# ------------------------------------------------------------
#  Data classes
# ------------------------------------------------------------

@dataclass
class Opl3OpParams:
    trem: int
    vib: int
    eg: int
    ksr: int
    mul: int
    ksl: int
    tl: int
    ar: int
    dr: int
    sl: int
    rr: int
    ws: int


@dataclass
class Opl3Features2Op:
    mod: Opl3OpParams
    car: Opl3OpParams
    fb: int
    alg: int

    # Derived features (for TX802 classifier etc.)
    bright: bool
    percussive: bool
    long_sustain: bool
    strong_fb: bool
    weak_fb: bool


@dataclass
class Opl3Instrument2Op:
    name: str
    regs: list[int]


# ------------------------------------------------------------
#  MoonBlaster 2OP OPLL instrument table (0–19)
# ------------------------------------------------------------

OPLL_OPL3_2OP_INSTRS: list[Opl3Instrument2Op] = [
    Opl3Instrument2Op("OPLL Violin",      [0x71,0x61,0x1E,0x00,0xD0,0x78,0x00,0x17,0x00,0x01,0x0E]),
    Opl3Instrument2Op("OPLL Guitar",      [0x13,0x41,0x1A,0x00,0xD8,0xF7,0x23,0x13,0x01,0x00,0x0A]),
    Opl3Instrument2Op("OPLL Piano",       [0x13,0x01,0x59,0x00,0xF2,0xC4,0x11,0x23,0x00,0x00,0x00]),
    Opl3Instrument2Op("OPLL Flute",       [0x31,0x61,0x0E,0x00,0xA8,0x64,0x70,0x27,0x00,0x00,0x0E]),
    Opl3Instrument2Op("OPLL Clarinet",    [0x32,0x21,0x1E,0x00,0xE0,0x76,0x00,0x28,0x00,0x00,0x0C]),
    Opl3Instrument2Op("OPLL Oboe",        [0x31,0x22,0x16,0x00,0xE0,0x71,0x00,0x18,0x00,0x00,0x0A]),
    Opl3Instrument2Op("OPLL Trumpet",     [0x21,0x61,0x1D,0x00,0x82,0x81,0x10,0x07,0x00,0x00,0x0E]),
    Opl3Instrument2Op("OPLL Organ",       [0x23,0x21,0x2D,0x00,0xA2,0x72,0x00,0x07,0x00,0x01,0x08]),
    Opl3Instrument2Op("OPLL Horn",        [0x61,0x61,0x1B,0x00,0x64,0x65,0x10,0x17,0x00,0x00,0x0C]),
    Opl3Instrument2Op("OPLL Synthesizer", [0x41,0x61,0x0B,0x00,0x85,0xF7,0x71,0x07,0x01,0x01,0x00]),
    Opl3Instrument2Op("OPLL Harpsichord", [0x13,0x01,0x43,0x00,0xFA,0xE4,0x10,0x04,0x00,0x01,0x02]),
    Opl3Instrument2Op("OPLL Vibraphone",  [0x17,0xC1,0x24,0x00,0xF8,0xF8,0x22,0x12,0x00,0x00,0x0E]),
    Opl3Instrument2Op("OPLL Synth. Bass", [0x61,0x50,0x0C,0x00,0xC2,0xF5,0x20,0x42,0x00,0x00,0x0A]),
    Opl3Instrument2Op("OPLL Acoust.Bass", [0x01,0x01,0x95,0x00,0xC9,0x95,0x03,0x02,0x00,0x00,0x06]),
    Opl3Instrument2Op("OPLL Elec.Guitar", [0x61,0x41,0x49,0x00,0xF1,0xE4,0x40,0x13,0x00,0x00,0x06]),
    Opl3Instrument2Op("BD1",              [0x28,0x21,0x03,0x00,0xFB,0xF6,0xFF,0xFF,0x00,0x05,0x0E]),
    Opl3Instrument2Op("SD1",              [0x06,0x02,0xC2,0x00,0x63,0xE8,0xE3,0xFC,0x03,0x06,0x0C]),
    Opl3Instrument2Op("TOM1",             [0xD2,0x43,0x09,0x00,0x78,0xFF,0x3C,0x06,0x05,0x02,0x0C]),
    Opl3Instrument2Op("CLOSED HH",        [0x3F,0xCF,0xC0,0x00,0xF1,0xD9,0x03,0xB8,0x02,0x00,0x0C]),
    Opl3Instrument2Op("CYM",              [0x67,0x78,0x1A,0x0C,0xE8,0xF7,0xF5,0xFA,0x00,0x06,0x08]),
]


# ------------------------------------------------------------
#  Register decoders
# ------------------------------------------------------------

def _decode_20(reg):
    return (reg >> 7) & 1, (reg >> 6) & 1, (reg >> 5) & 1, (reg >> 4) & 1, reg & 0x0F

def _decode_40(reg):
    return (reg >> 6) & 3, reg & 0x3F

def _decode_60(reg):
    return (reg >> 4) & 0x0F, reg & 0x0F

def _decode_80(reg):
    return (reg >> 4) & 0x0F, reg & 0x0F

def _decode_e0(reg):
    return reg & 0x07

def _decode_c0(reg):
    return (reg >> 1) & 0x07, reg & 0x01


# ------------------------------------------------------------
#  Feature extractor
# ------------------------------------------------------------

def extract_opl3_2op_features(regs: list[int]) -> Opl3Features2Op:
    m20, c20 = regs[0], regs[1]
    m40, c40 = regs[2], regs[3]
    m60, c60 = regs[4], regs[5]
    m80, c80 = regs[6], regs[7]
    me0, ce0 = regs[8], regs[9]
    c0        = regs[10]

    # Operator decode
    m_trem, m_vib, m_eg, m_ksr, m_mul = _decode_20(m20)
    c_trem, c_vib, c_eg, c_ksr, c_mul = _decode_20(c20)

    m_ksl, m_tl = _decode_40(m40)
    c_ksl, c_tl = _decode_40(c40)

    m_ar, m_dr = _decode_60(m60)
    c_ar, c_dr = _decode_60(c60)

    m_sl, m_rr = _decode_80(m80)
    c_sl, c_rr = _decode_80(c80)

    m_ws = _decode_e0(me0)
    c_ws = _decode_e0(ce0)

    fb, alg = _decode_c0(c0)

    mod = Opl3OpParams(m_trem, m_vib, m_eg, m_ksr, m_mul,
                       m_ksl, m_tl, m_ar, m_dr, m_sl, m_rr, m_ws)
    car = Opl3OpParams(c_trem, c_vib, c_eg, c_ksr, c_mul,
                       c_ksl, c_tl, c_ar, c_dr, c_sl, c_rr, c_ws)

    # Derived features
    bright = (car.tl <= 24) or (mod.tl <= 24)
    percussive = (car.ar >= 12) and (car.sl <= 3)
    long_sustain = (car.sl >= 8)
    strong_fb = fb >= 4
    weak_fb = fb == 0

    return Opl3Features2Op(
        mod=mod,
        car=car,
        fb=fb,
        alg=alg,
        bright=bright,
        percussive=percussive,
        long_sustain=long_sustain,
        strong_fb=strong_fb,
        weak_fb=weak_fb,
    )


