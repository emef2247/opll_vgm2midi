from __future__ import annotations
import sys
import os

from opll import (
    NUM_CH,
    RHYTHM_CH_MAP,
    RHYTHM_VOICE_ID_MAP,
    RHYTHM_VOICE_ID_MAP_RX21,
)

from segment_utils import (
    compute_velocity
)

from midi_utils import (
    DEFAULT_PPQ,
    MidiBuilder,
    normalize_scale,
    map_gm_drum,
    map_rx21_drum,
    _is_zero_patch,
    _tempo_meta_event,
    _track_name_meta_event,
    _vgm_tick_to_midi_tick,
    _opll_vol_to_velocity,
    _at_token_to_user_v_num,
    _segment_to_midi_note,
    compute_cc11,
)

# User patches are assigned GM programs starting from this value (0-indexed).
# Programs 0-14 correspond to OPLL presets 1-15 via OPLL_TO_GM_PROGRAM.
# Programs 15-19 are reserved for rhythm channels (bd/sd/tom/tc/hh) in MS2
# convention (INST 16-20).  User patches therefore start at program 20
# (= GM program 21 in 1-indexed / musician notation).
_USER_VOICE_FIRST_GM_PROGRAM = 20

_GM_PROGRAM_UNUSED = 127   # GM 127 = Gunshot (0-indexed)


# ============================================================
# Default GM TX802 Default table based conversion
# ============================================================
#   1: OPLL Violin          -> TX802 A11 Strings        → GM Strings
#   2: OPLL Guitar          -> TX802 A36 RubbaRoad      → GM Jazz Guitar
#   3: OPLL Piano           -> TX802 A33 Piano1         → GM Electric Piano 1
#   4: OPLL Flute           -> TX802 A23 Flute          → GM Flute
#   5: OPLL Clarinet        -> TX802 B40 ClariSolo      → GM Clarinet
#   6: OPLL Oboe            -> TX802 A20 Bassoon        → GM Bassoon
#   7: OPLL Trumpet         -> TX802 A8 SilvaTrmpt      → GM Trumpet
#   8: OPLL Organ           -> TX802 A48 TouchOrga      → GM Rock Organ
#   9: OPLL Horn            -> TX802 A10 FrenchHorn     → GM French Horn
#   10: OPLL Synth          -> TX802 A38 FullTines      → GM Electric Piano 1
#   11: OPLL Harpsichord    -> TX802 A41 Clavecin       → GM Harpsichord
#   12: OPLL Vibraphone     -> TX802 B21 VibraPhone     → GM Vibraphone
#   13: OPLL SynthBass      -> TX802 B3 SkweekBass      → GM Synth Bass 1
#   14: OPLL AcousticBass   -> TX802 B2 StringBass      → GM Acoustic Bass
#   15: OPLL ElectricGuitar -> TX802 B11 FingaPicka     → GM Electric Guitar (clean)

GM_MELODY_OPLL_TO_DEFAULT = {
    1: 48,  # A11 Strings        → GM Strings
    2: 27,  # A36 RubbaRoad      → GM Jazz Guitar
    3: 4,   # A33 Piano1         → GM Electric Piano 1
    4: 73,  # A23 Flute          → GM Flute
    5: 71,  # B40 ClariSolo      → GM Clarinet
    6: 70,  # A20 Bassoon        → GM Bassoon
    7: 56,  # A8 SilvaTrmpt      → GM Trumpet
    8: 19,  # A48 TouchOrga      → GM Rock Organ
    9: 60,  # A10 FrenchHorn     → GM French Horn
    10: 4,  # A38 FullTines      → GM Electric Piano 1
    11: 6,  # A41 Clavecin       → GM Harpsichord
    12: 11, # B21 VibraPhone     → GM Vibraphone
    13: 38, # B3 SkweekBass      → GM Synth Bass 1
    14: 32, # B2 StringBass      → GM Acoustic Bass
    15: 27, # B11 FingaPicka     → GM Electric Guitar (clean)
}

# ============================================================
# OPLL → GM Voice Characteristic Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> 49 GM Strings2
#   2: OPLL Guitar          -> 28 GM Clean Guitar
#   3: OPLL Piano           ->  5 GM EP2
#   4: OPLL Flute           -> 68 GM Oboe
#   5: OPLL Clarinet        -> 70 GM Bassoon
#   6: OPLL Oboe            -> 71 GM Clarinet
#   7: OPLL Trumpet         -> 61 GM Brass1
#   8: OPLL Organ           -> 12 GM Marimba
#   9: OPLL Horn            -> 63 GM SynthBrass1
#   10: OPLL Synth          -> 82 GM Lead2 (Saw)
#   11: OPLL Harpsichord    ->  8 GM Clavinet
#   12: OPLL Vibraphone     -> 14 GM Tubular Bells
#   13: OPLL SynthBass      -> 36 GM Slap Bass 1
#   14: OPLL AcousticBass   -> 37 GM Slap Bass 2
#   15: OPLL ElectricGuitar -> 81 GM Lead1 (Square)

GM_MELODY_OPLL_TO_GM = {
    1: 49,  # Strings2
    2: 28,  # Clean Guitar
    3: 5,   # EP2
    4: 68,  # Oboe
    5: 70,  # Bassoon
    6: 71,  # Clarinet
    7: 61,  # Brass1
    8: 12,  # Marimba
    9: 63,  # SynthBrass1
    10: 82, # Lead2 (Saw)
    11: 8,  # Clavinet
    12: 14, # Tubular Bells
    13: 36, # Slap Bass 1
    14: 37, # Slap Bass 2
    15: 81, # Lead1 (Square)
}

# ============================================================
# OPLL → GM Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> 40 GM Violin
#   2: OPLL Guitar          -> 25 GM Nylon Guitar
#   3: OPLL Piano           ->  0 GM Acoustic Grand Piano
#   4: OPLL Flute           -> 73 GM Flute
#   5: OPLL Clarinet        -> 71 GM Clarinet
#   6: OPLL Oboe            -> 68 GM Oboe
#   7: OPLL Trumpet         -> 56 GM Trumpet
#   8: OPLL Organ           -> 19 GM Rock Organ
#   9: OPLL Horn            -> 60 GM French Horn
#   10: OPLL Synth          -> 81 GM Lead1 (Square)
#   11: OPLL Harpsichord    ->  6 GM Harpsichord
#   12: OPLL Vibraphone     -> 11 GM Vibraphone
#   13: OPLL SynthBass      -> 38 GM Synth Bass 1
#   14: OPLL AcousticBass   -> 32 GM Acoustic Bass
#   15: OPLL ElectricGuitar -> 27 GM Clean Guitar

GM_MELODY_OPLL_TO_OPLL = {
    1: 40,  # Violin
    2: 25,  # Nylon Guitar
    3: 0,   # Acoustic Grand Piano
    4: 73,  # Flute
    5: 71,  # Clarinet
    6: 68,  # Oboe
    7: 56,  # Trumpet
    8: 19,  # Rock Organ
    9: 60,  # French Horn
    10: 81, # Lead1 (Square)
    11: 6,  # Harpsichord
    12: 11, # Vibraphone
    13: 38, # Synth Bass 1
    14: 32, # Acoustic Bass
    15: 27, # Clean Guitar
}


# ============================================================
# CUSTOM1 GM Voice Name Based Mapping Table
# ============================================================
#   1: OPLL Violin          -> 48 GM Strings
#   2: OPLL Guitar          -> 27 GM Jazz Guitar
#   3: OPLL Piano           ->  4 GM Electric Piano 1
#   4: OPLL Flute           -> 73 GM Flute
#   5: OPLL Clarinet        -> 71 GM Clarinet
#   6: OPLL Oboe            -> 68 GM Oboe
#   7: OPLL Trumpet         -> 56 GM Trumpet
#   8: OPLL Organ           -> 19 GM Rock Organ
#   9: OPLL Horn            -> 60 GM French Horn
#   10: OPLL Synth          -> 81 GM Lead1 (Square)
#   11: OPLL Harpsichord    ->  6 GM Harpsichord
#   12: OPLL Vibraphone     -> 11 GM Vibraphone
#   13: OPLL SynthBass      -> 38 GM Synth Bass 1
#   14: OPLL AcousticBass   -> 32 GM Acoustic Bass
#   15: OPLL ElectricGuitar -> 27 GM Electric Guitar (clean)

GM_MELODY_OPLL_TO_CUSTOM1 = {
    1: 48,  # Violin → GM Strings
    2: 27,  # Guitar → GM Jazz Guitar
    3: 4,   # Piano → GM Electric Piano 1
    4: 73,  # Flute → GM Flute
    5: 71,  # Clarinet → GM Clarinet
    6: 68,  # Oboe → GM Oboe
    7: 56,  # Trumpet → GM Trumpet
    8: 19,  # Organ → GM Rock Organ
    9: 60,  # Horn → GM French Horn
    10: 81, # Synth → GM Lead1 (Square)
    11: 6,  # Harpsichord → GM Harpsichord
    12: 11, # Vibraphone → GM Vibraphone
    13: 38, # SynthBass → GM Synth Bass 1
    14: 32, # AcousticBass → GM Acoustic Bass
    15: 27, # ElectricGuitar → GM Electric Guitar (clean)
}


def get_gm_melody_voice(opll_patch: int, melody_mode: str = "default") -> int:
    """
    Return GM program number (0–127) for given OPLL patch.
    """

    tables = {
        "default": GM_MELODY_OPLL_TO_DEFAULT,
        "name": GM_MELODY_OPLL_TO_GM,
    }

    melody_mode = melody_mode.lower()
    table = tables.get(melody_mode, GM_MELODY_OPLL_TO_DEFAULT)

    # fallback は DEFAULT の 1 番（Strings）
    return table.get(opll_patch, table.get(1, 48))

postfix_table = {
    ("default", "gm"): "G",
    ("default", "rx21"): "R",
    ("gm", "gm"): "GG",
    ("gm", "rx21"): "GR",
    ("opll", "gm"): "OG",
    ("opll", "rx21"): "OR",
}


def _build_user_voice_gm_map(
    user_patches: dict[int, bytes],
    existing_map: dict[str, int],
) -> tuple[dict[int, int], dict[str, int]]:
    """Build at_v_num -> GM program (0-indexed) for all user patches.

    Special cases:
    - All-zero patch (no register writes): always mapped to GM 127 (Gunshot),
      regardless of ``existing_map``.  This is a sentinel for "unused" patches.

    For other patches already present in *existing_map* the stored program is used.
    New non-zero patches are assigned the next free program >= ``_USER_VOICE_FIRST_GM_PROGRAM``
    in encounter order.

    Returns:
        at_v_to_gm   : dict mapping at_v_num (int) -> GM program (0-indexed int)
        updated_map  : updated patch_hex -> GM program dict (superset of existing_map)
    """
    at_v_to_gm: dict[int, int] = {}
    updated = dict(existing_map)

    used_programs: set[int] = set(existing_map.values())
    # Reserve GM 127 for zero patches; exclude from free-assignment pool
    used_programs.add(_GM_PROGRAM_UNUSED)

    def _next_free() -> int:
        p = _USER_VOICE_FIRST_GM_PROGRAM
        while p in used_programs:
            p += 1
        used_programs.add(p)
        return p

    for at_v_num, patch_bytes in user_patches.items():
        patch_hex = patch_bytes.hex()
        # All-zero patch is always GM 127 (unused sentinel), not editable
        if _is_zero_patch(patch_bytes):
            at_v_to_gm[at_v_num] = _GM_PROGRAM_UNUSED
            updated[patch_hex] = _GM_PROGRAM_UNUSED
            continue
        if patch_hex in updated:
            at_v_to_gm[at_v_num] = updated[patch_hex]
        else:
            gm_prog = _next_free()
            updated[patch_hex] = gm_prog
            at_v_to_gm[at_v_num] = gm_prog

    return at_v_to_gm, updated


def compute_velocity_gm(seg):
    opll_vol = getattr(seg, "vol", 15)
    x = opll_vol / 15.0

    # GM は PCM なので線形に近い
    v = int(127 * x)

    # 軽いリフト（自然な聞こえ方）
    if v < 40:
        v = int(v * 1.2)

    return max(1, min(127, v))



def get_gm_melody_voice(opll_patch: int, melody_mode: str = "gm") -> int:
    tables = {
        "default": GM_MELODY_OPLL_TO_DEFAULT,
        "name": GM_MELODY_OPLL_TO_GM,
        "custom1": GM_MELODY_OPLL_TO_OPLL,
    }

    table = tables.get(melody_mode, GM_MELODY_OPLL_TO_GM)

    # OPLL patch が範囲外なら fallback=0 の音色を返す
    return table.get(opll_patch, table.get(0, 81))


def compute_portamento_time_gm(prev_note, next_note, tick_length, bpm, ppq):
    # 音程差（半音）
    diff = abs(next_note - prev_note)

    # ノート長（秒）
    sec = tick_length * (60.0 / (bpm * ppq))

    # GM の CC5 は 係数を下げる　(TX802と比較して弱い)
    base = diff * 1.2

    # ノート長による補正（マイルド）
    if sec < 0.2:
        base *= 0.7
    elif sec > 0.5:
        base *= 1.15

    # GM の CC5 は 0〜127
    return int(max(1, min(127, base)))

def midi_builder_gm(
    segments_by_ch: dict,
    bpm: int,
    ppq: int = DEFAULT_PPQ,
    track_name: str = "vgm2midi",
    user_voice_gm_map: dict[int, int] | None = None,
    melody_mode: str = "gm",
    rhythm_mode: str = "gm"
) -> MidiBuilder:

    builder = MidiBuilder(ppq=ppq)
    builder.add_event(0, _tempo_meta_event(bpm), order=0)
    builder.add_event(0, _track_name_meta_event(track_name), order=1)

    last_program_by_ch: dict[int, int] = {}
    last_note_by_ch: dict[int, int] = {}

    # GM Drum channel = CH9
    GM_DRUM_CH = 9

    # ------------------------------------------------------------
    # CH0〜CH15 を GM 仕様に従って処理
    # ------------------------------------------------------------
    for ch in range(16):

        # ------------------------------------------------------------
        # ★ GM Drum Channel (CH9)
        # ------------------------------------------------------------
        if ch == GM_DRUM_CH:
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

                    vel = compute_velocity_gm(seg)

                    builder.add_event(start_tick, bytes([0x99, drum_note, vel]), order=30)
                    builder.add_event(end_tick,   bytes([0x89, drum_note, 0]),   order=40)

            continue

        # ------------------------------------------------------------
        # ★ Melody channels (CH0〜CH15 except CH9)
        # ------------------------------------------------------------
        for seg in segments_by_ch.get(ch, []):
            if int(getattr(seg, "keyon", 0)) != 1:
                continue

            start_tick = _vgm_tick_to_midi_tick(getattr(seg, "tick_start", 0), bpm, ppq)
            end_tick   = _vgm_tick_to_midi_tick(getattr(seg, "tick_end",   0), bpm, ppq)
            if end_tick <= start_tick:
                continue

            inst = int(getattr(seg, "inst", 0))

            # ------------------------------------------------------------
            # inst==0 → @vN user patch
            # ------------------------------------------------------------
            if inst == 0 and user_voice_gm_map:
                at_token = getattr(seg, "at_token", "") or ""
                at_v_num = _at_token_to_user_v_num(at_token)

                if at_v_num is not None and at_v_num in user_voice_gm_map:
                    program = user_voice_gm_map[at_v_num]
                else:
                    program = get_gm_melody_voice(0, melody_mode)
            else:
                program = get_gm_melody_voice(inst, melody_mode)

            # Program Change
            if last_program_by_ch.get(ch) != program:
                builder.add_event(start_tick, bytes([0xC0 | ch, program]), order=10)
                last_program_by_ch[ch] = program

            midi_note = _segment_to_midi_note(seg)
            if midi_note is None:
                continue

            vel = compute_velocity_gm(seg)

            # Portamento
            is_portamento = int(getattr(seg, "is_portamento", 0))
            if is_portamento == 1 and ch in last_note_by_ch:
                prev_note = last_note_by_ch[ch]

                try:
                    mode_ioi = int(getattr(seg, "mode_ioi", 2))
                except:
                    mode_ioi = 2

                try:
                    seg_l = int(getattr(seg, "l", 2))
                except:
                    seg_l = 2

                #portamento_time = min(127, max(1, seg_l * 64 // max(1, mode_ioi)))
                portamento_time = compute_portamento_time_gm(prev_note, midi_note, end_tick - start_tick, bpm, ppq)

                builder.add_event(start_tick, bytes([0xB0 | ch, 84, prev_note]), order=15)
                builder.add_event(start_tick, bytes([0xB0 | ch, 65, 127]), order=16)
                builder.add_event(start_tick, bytes([0xB0 | ch, 5, portamento_time]), order=17)
                builder.add_event(end_tick,   bytes([0xB0 | ch, 65, 0]), order=35)

            # CC11 Expression
            cc11 = 127
            builder.add_event(start_tick, bytes([0xB0 | ch, 11, cc11]), order=18)

            # Note On
            #velocity = compute_velocity(seg)
            velocity = compute_velocity_gm(seg)
            builder.add_event(start_tick, bytes([0x90 | ch, midi_note, velocity]), order=20)

            # Note Off
            builder.add_event(end_tick, bytes([0x80 | ch, midi_note, 0]), order=40)

            last_note_by_ch[ch] = midi_note

    return builder
