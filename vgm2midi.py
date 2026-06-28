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
import argparse
from dataclasses import dataclass
import random
random.seed(0)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, 'py'))

from py.vgm_reader import (
    parse_vgm
)

from py.opll import (
    RHYTHM_CH_MAP,
    parse_opll_regs_for_rhythm,
    _build_segments,
)

from py.midi_utils import (
    DEFAULT_PPQ,
    MidiBuilder,
    _assign_voice_ids,
    _user_voice_map_path,
    _load_user_voice_map,
    _save_user_voice_map,
    _is_zero_patch,
    _format_user_patch_lines,
)

from py.gm import (
    midi_builder_gm,
    _build_user_voice_gm_map
)

from py.tx802 import (
    midi_builder_tx802,
    tx802_bank_voice_to_vnum,
    _build_user_voice_tx802_map,
    _reverse_lookup_tx802_voice,
    _format_user_patch_lines_tx802,
    _load_user_voice_tx802_map,
    _user_voice_tx802_map_path,
    _save_user_voice_tx802_map,
    build_tx802_voice_sysex,
    save_tx802_voice_syx
)

def build_output_filename(stim: str, target: str,melody_mode: str, rhythm_mode: str) -> str:
    """
    Return output filename: <stim><PostFix>.mid
    """

    postfix_table = {
        ("tx802", "default", "gm"): "_tx802_default_gm",
        ("tx802", "default", "rx21"): "_tx802_default_rx21",
        ("tx802", "name", "gm"): "_gm_name_gm",
        ("tx802", "name", "rx21"): "_gm_name_rx21",
        ("gm", "default", "gm"): "_gm_default_gm",
        ("gm", "default", "rx21"): "_gm_default_rx21",
        ("gm", "name", "gm"): "_gm_name_gm",
        ("gm", "name", "rx21"): "_gm_name_rx21",
    }

    # typo に強くする
    melody_mode = melody_mode.lower()
    rhythm_mode = rhythm_mode.lower()

    # fallback は Non
    postfix = postfix_table.get((target,melody_mode, rhythm_mode), "non")

    return f"{stim}{postfix}.mid"

def process_vgm_to_midi(
    vgm_path: str,
    output_dir: str | None = None,
    ppq: int = DEFAULT_PPQ,
    target: str = "gm",
    melody_mode: str = "default",
    rhythm_mode: str ="gm",
    debug: bool = False,
) -> str:
    base_name = os.path.splitext(os.path.basename(vgm_path))[0]
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(os.path.abspath(vgm_path)),
        )
    os.makedirs(output_dir, exist_ok=True)
    (
        opll_log_csv,
        opll_trace_csv,
        opll_voice_csv,
        opll_regs_csv,
    ) = parse_vgm(vgm_path, output_dir)

    rhythm_timeline = []
    if opll_regs_csv and os.path.exists(opll_regs_csv):
        rhythm_timeline = parse_opll_regs_for_rhythm(opll_regs_csv)

    segments_by_ch, bpm_detected = _build_segments(
        opll_trace_csv,
        include_rhythm=True,
        rhythm_reg_timeline=rhythm_timeline,
        debug=debug,
    )

    if debug:
        print(f"[vgm2midi] bpm={bpm_detected}")

    # ── Assign voice IDs (captures user patches) ──────────────────────────
    _voice_table, user_patches, _warnings = _assign_voice_ids(segments_by_ch, opll_voice_csv)

    # Track　name
    fname = build_output_filename(base_name, target, melody_mode, rhythm_mode)
    track_name = f"{fname}: --target={target} --melody_mode={melody_mode} --rhythm_mode={rhythm_mode}"

    # Generate the track
    if target=="gm":
        # ── Resolve user-patch GM program mapping ─────────────────────────────
        user_voice_gm_map: dict[int, int] | None = None
        if user_patches:
            # <stem>.user_voice.json lives beside <stem>.mid
            uv_path = _user_voice_map_path(output_dir, base_name)
            existing_map = _load_user_voice_map(uv_path)
            user_voice_gm_map, updated_map = _build_user_voice_gm_map(user_patches, existing_map)
            _save_user_voice_map(uv_path, updated_map, user_patches, user_voice_gm_map)

            # Print user patch info to stdout.
            # All-zero patches are shown as a brief unused notice; real patches get full decode.
            real_patches = {k: v for k, v in user_patches.items() if not _is_zero_patch(v)}
            zero_patches = {k: v for k, v in user_patches.items() if _is_zero_patch(v)}
            total = len(user_patches)
            print(f"User patches ({total}) -> {uv_path}")
            for at_v_num in sorted(real_patches):
                patch_bytes = real_patches[at_v_num]
                gm_prog = user_voice_gm_map[at_v_num]
                for line in _format_user_patch_lines(at_v_num, patch_bytes, gm_prog):
                    print(line)
            for at_v_num in sorted(zero_patches):
                gm_prog = user_voice_gm_map[at_v_num]
                print(
                    f"User patch v{at_v_num}: all-zero (no register written) -> "
                    f"GM program {gm_prog} (1-indexed:{gm_prog + 1}, unused)"
                )
        
        builder = midi_builder_gm(
            segments_by_ch,
            bpm=bpm_detected,
            ppq=ppq,
            track_name=track_name,
            melody_mode=melody_mode,
            rhythm_mode=rhythm_mode,
            user_voice_gm_map=user_voice_gm_map,
        )

        midi_bytes = builder.build()
        out_path = os.path.join(output_dir, f"{fname}")
        with open(out_path, "wb") as fh:
            fh.write(midi_bytes)

        if not debug:
            for _csv in [opll_log_csv, opll_trace_csv, opll_voice_csv, opll_regs_csv]:
                try:
                    if _csv and os.path.isfile(_csv):
                        os.remove(_csv)
                except OSError:
                    pass


    if target == "tx802":
        user_voice_tx802_map = None

        if user_patches:
            uv_path = _user_voice_tx802_map_path(output_dir, base_name)
            existing_map = _load_user_voice_tx802_map(uv_path)

            user_voice_tx802_map, updated_map = _build_user_voice_tx802_map(user_patches, existing_map)
            _save_user_voice_tx802_map(uv_path, updated_map)

            # ログ出力（TX802 版）
            print(f"User patches ({len(user_patches)}) -> {uv_path}")
            for at_v_num, patch_bytes in user_patches.items():
                tx802_prog = user_voice_tx802_map[at_v_num]
                vnum = tx802_bank_voice_to_vnum(tx802_prog["bank"], tx802_prog["voice"])
                tx802_voice = _reverse_lookup_tx802_voice(vnum)

                for line in _format_user_patch_lines_tx802(
                    at_v_num, patch_bytes, tx802_prog, tx802_voice, vnum
                ):
                    print(line)


            # TX802 Voice SysExのテスト
            txv_params = {
                "op1": {"ar":9,"dr":0,"sl":0,"rr":3,"tl":10,"rs":0,"dt":0,"mul":1,"am":0},
                "op2": {"ar":10,"dr":4,"sl":15,"rr":5,"tl":14,"rs":0,"dt":0,"mul":3,"am":0},
                "fb": 0,
                "alg": 0
            }

            syx = build_tx802_voice_sysex(txv_params, name="OPLL15")
            save_tx802_voice_syx("OPLL15.syx", syx)


        # TX802 用 MIDI を生成
        builder = midi_builder_tx802(
            segments_by_ch,
            bpm=bpm_detected,
            ppq=ppq,
            track_name=track_name,
            melody_mode=melody_mode,
            rhythm_mode=rhythm_mode,
            user_voice_tx802_map=user_voice_tx802_map,
        )

        midi_bytes = builder.build()
        fname = build_output_filename(base_name, target,melody_mode, rhythm_mode)
        out_path = os.path.join(output_dir, f"{fname}")
        with open(out_path, "wb") as fh:
            fh.write(midi_bytes)

        if not debug:
            for _csv in [opll_log_csv, opll_trace_csv, opll_voice_csv, opll_regs_csv]:
                try:
                    if _csv and os.path.isfile(_csv):
                        os.remove(_csv)
                except OSError:
                    pass
    return out_path

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert VGM (YM2413) to MIDI (SMF format 0)")
    parser.add_argument("vgm_file", help="Input VGM file path")
    parser.add_argument(
        "--outdir", default=None,
        help="Output directory (default: same directory as VGM file)",
    )
    parser.add_argument(
        "--ppq",
        type=int,
        default=DEFAULT_PPQ,
        metavar="N",
        help=f"MIDI ticks per quarter note (default: {DEFAULT_PPQ})",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print extra information and keep intermediate CSV files",
    )
    parser.add_argument(
        "--target",
        choices=["gm", "tx802"],
        default="gm",
        help="MIDI target: gm (General MIDI) or tx802 (Yamaha TX802)")

    parser.add_argument(
        "--melody_mode",
        choices=["default","name"],
        default="default",
        help="Mapping style for melody voice  : gm (General MIDI) or MoonBlaster (Closer OPLL Preset)")
    
    parser.add_argument(
        "--rhythm_mode",
        choices=["gm", "rx21"],
        default="gm",
        help="MIDI rhythm_mode: gm (General MIDI) or RX21 (Yamaha RX21)")
    
    args = parser.parse_args()

    if args.ppq <= 0:
        parser.error("--ppq must be >= 1")

    if not os.path.isfile(args.vgm_file):
        parser.error(f"vgm_file not found: {args.vgm_file}")

    out_path = process_vgm_to_midi(
        args.vgm_file,
        output_dir=args.outdir,
        ppq=args.ppq,
        target=args.target,
        melody_mode=args.melody_mode,
        rhythm_mode=args.rhythm_mode,
        debug=args.debug,
    )
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
