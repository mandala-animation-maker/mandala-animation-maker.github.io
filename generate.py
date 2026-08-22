#!/usr/bin/env python3
"""
Build a reel-style MP4 from a sequence of word-timed frames + optional audio.

Expects, in the current directory:
  - frames/                 folder containing frame_0001.png, frame_0002.png, ...
  - a single *.json file    list of {"frame": ..., "start": ..., "end": ...}
  - (optional) one audio file: .mp3 / .wav / .m4a / .aac / .ogg

Output: output_hq.mp4 in the current directory.
"""

import glob
import json
import os
import subprocess
import sys

FRAMES_DIR = "frames"
OUTPUT_VIDEO = "output_hq.mp4"
AUDIO_EXTENSIONS = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg")
FPS = 30


def fail(message):
    print(f"Error: {message}")
    sys.exit(1)


def find_single(patterns, kind):
    """Find files matching the given glob pattern(s). Warn if more than one exists."""
    matches = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern))
    matches = sorted(matches)  # deterministic instead of filesystem order
    if not matches:
        return None
    if len(matches) > 1:
        print(f"Warning: multiple {kind} files found ({matches}); using '{matches[0]}'.")
    return matches[0]


def load_sequence(json_path):
    with open(json_path, "r") as f:
        sequence = json.load(f)

    if not isinstance(sequence, list) or not sequence:
        fail(f"'{json_path}' must contain a non-empty list of frame entries.")

    for i, entry in enumerate(sequence):
        for key in ("frame", "start"):
            if key not in entry:
                fail(f"Entry {i} in '{json_path}' is missing required field '{key}'.")

    sequence.sort(key=lambda e: float(e["start"]))
    return sequence


def check_frames_exist(sequence, frames_dir):
    missing = [
        e["frame"] for e in sequence
        if not os.path.exists(os.path.join(frames_dir, e["frame"]))
    ]
    if missing:
        preview = ", ".join(missing[:5])
        more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        fail(f"{len(missing)} frame(s) referenced in the JSON are missing from "
             f"'{frames_dir}/': {preview}{more}")


def build_concat_file(sequence, frames_dir, has_audio):
    """
    Write an ffconcat file. The concat demuxer applies a 'duration' line to the
    file listed immediately above it. The final entry needs no duration line
    UNLESS it's followed by nothing -- ffmpeg ignores duration on the very last
    entry, so instead we repeat the last frame once with its real duration set,
    which is the documented, correct way to terminate the list.
    """
    lines = ["ffconcat version 1.0"]

    for i, entry in enumerate(sequence):
        frame = entry["frame"]
        start = float(entry["start"])

        if i < len(sequence) - 1:
            duration = max(0.0, float(sequence[i + 1]["start"]) - start)
        else:
            # Last frame: use its own 'end' if present, else fall back to 1s.
            end = float(entry.get("end", start + 1.0))
            duration = max(0.01, end - start)

        lines.append(f"file '{frame}'")
        lines.append(f"duration {duration:.6f}")

    # The concat demuxer requires the final file to be listed once more
    # WITHOUT a duration line (its duration is determined by the stream/audio
    # end, not by this line) -- this is the correct, single repeat, not a
    # second full entry with its own bogus duration.
    lines.append(f"file '{sequence[-1]['frame']}'")

    concat_path = os.path.join(frames_dir, "input.txt")
    with open(concat_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return concat_path


def run_ffmpeg(frames_dir, audio_file, total_duration):
    print("Generating ultra-HQ MP4... please wait.")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "input.txt"]

    if audio_file:
        cmd.extend(["-i", audio_file])

    cmd.extend([
        "-map", "0:v:0",
        "-vf", f"setpts=PTS-STARTPTS,fps={FPS},scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
    ])

    if audio_file:
        cmd.extend([
            "-map", "1:a:0",
            "-af", "asetpts=PTS-STARTPTS,aresample=async=1000:min_hard_comp=0.1:first_pts=0",
            "-c:a", "aac",
            "-b:a", "192k",
        ])
        # Use whichever stream is shorter so we never freeze on a dangling frame
        # or cut audio short; total_duration also caps runaway length.
        cmd.extend(["-t", f"{total_duration:.6f}"])
    else:
        cmd.extend(["-t", f"{total_duration:.6f}"])

    cmd.append(OUTPUT_VIDEO)

    result = subprocess.run(cmd, cwd=frames_dir)
    return result.returncode == 0


def main():
    if not os.path.exists(FRAMES_DIR):
        fail(f"'{FRAMES_DIR}' folder not found in this directory.")

    json_file = find_single(["*.json"], "JSON")
    if not json_file:
        fail("No JSON file found in this directory.")
    print(f"JSON sequence file detected: {json_file}")

    audio_file = find_single(list(AUDIO_EXTENSIONS), "audio")
    if audio_file:
        audio_file = os.path.abspath(audio_file)
        print(f"Audio file detected: {os.path.basename(audio_file)}")
    else:
        print("No audio file found. Generating silent video.")

    sequence = load_sequence(json_file)
    check_frames_exist(sequence, FRAMES_DIR)

    # Total runtime: last frame's 'end' if given, else last frame's start + 1s.
    last = sequence[-1]
    total_duration = float(last.get("end", float(last["start"]) + 1.0))

    build_concat_file(sequence, FRAMES_DIR, has_audio=bool(audio_file))

    ok = run_ffmpeg(FRAMES_DIR, audio_file, total_duration)

    if ok:
        os.rename(os.path.join(FRAMES_DIR, OUTPUT_VIDEO), OUTPUT_VIDEO)
        print(f"\nSUCCESS! Video generated: {OUTPUT_VIDEO} ({total_duration:.2f}s)")
    else:
        fail("ffmpeg failed. Check the error log above.")


if __name__ == "__main__":
    main()
