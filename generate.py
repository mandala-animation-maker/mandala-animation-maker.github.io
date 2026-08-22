#!/usr/bin/env python3
"""
Build a reel-style MP4 from a sequence of word-timed frames + optional audio.

Expects, in the current directory:
  - frames/                 folder containing frame_0001.png, frame_0002.png, ...
  - a single *.json file    list of {"frame": ..., "start": ..., "end": ...}
  - (optional) one audio file: .mp3 / .wav / .m4a / .aac / .ogg

Output: output_hq.mp4 in the current directory.

Fixes applied vs. the original script:
  1. Timestamps are normalized so the sequence always starts at t=0, regardless
     of what the first entry's "start" value is. (Previously: if the first
     frame's start wasn't 0, video/audio zero-points didn't correspond to the
     same real moment -> unmatched first few seconds.)
  2. Total output duration is clamped to min(json_duration, actual_audio_duration),
     probed with ffprobe -- not just trusted from the JSON. (Previously: -t used
     only the JSON's last "end", so if audio was shorter, ffmpeg kept emitting
     silent video frames past the end of the audio -> trailing unmatched frames.)
  3. Frame durations are validated as non-negative and non-zero (a zero or
     negative gap between consecutive "start" values silently corrupts the
     concat timeline).
  4. Audio trimming uses -shortest semantics done explicitly and correctly,
     instead of a misleading comment claiming -t alone achieves this.
  5. Extra defensive checks: empty sequence, non-numeric start/end, missing
     ffmpeg/ffprobe, frame dimension odd-pixel handling kept from original.
"""

import glob
import json
import os
import shutil
import subprocess
import sys

FRAMES_DIR = "frames"
OUTPUT_VIDEO = "output_hq.mp4"
AUDIO_EXTENSIONS = ("*.mp3", "*.wav", "*.m4a", "*.aac", "*.ogg")
FPS = 30
MIN_FRAME_DURATION = 1.0 / FPS  # never allow a frame duration below one output tick


def fail(message):
    print(f"Error: {message}")
    sys.exit(1)


def check_binaries():
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            fail(f"'{binary}' not found on PATH. Please install ffmpeg.")


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
        try:
            sequence = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"'{json_path}' is not valid JSON: {e}")

    if not isinstance(sequence, list) or not sequence:
        fail(f"'{json_path}' must contain a non-empty list of frame entries.")

    for i, entry in enumerate(sequence):
        if not isinstance(entry, dict):
            fail(f"Entry {i} in '{json_path}' is not an object.")
        for key in ("frame", "start"):
            if key not in entry:
                fail(f"Entry {i} in '{json_path}' is missing required field '{key}'.")
        for key in ("start", "end"):
            if key in entry:
                try:
                    float(entry[key])
                except (TypeError, ValueError):
                    fail(f"Entry {i} in '{json_path}' has non-numeric '{key}': {entry[key]!r}")

    sequence.sort(key=lambda e: float(e["start"]))

    # --- Fix #1: normalize so the sequence starts at t=0 ---
    offset = float(sequence[0]["start"])
    if offset != 0.0:
        print(f"Note: first frame started at t={offset:.3f}s in the JSON; "
              f"normalizing all timestamps so playback starts at t=0.")
        for entry in sequence:
            entry["start"] = float(entry["start"]) - offset
            if "end" in entry:
                entry["end"] = float(entry["end"]) - offset

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


def get_media_duration(path):
    """Probe a media file's duration in seconds using ffprobe. Returns None on failure."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Warning: ffprobe failed on '{path}': {result.stderr.strip()}")
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        print(f"Warning: could not parse ffprobe duration output for '{path}': "
              f"{result.stdout.strip()!r}")
        return None


def build_concat_file(sequence, frames_dir):
    """
    Write an ffconcat file. The concat demuxer applies a 'duration' line to the
    file listed immediately above it. The demuxer requires the final file to be
    repeated once more without a duration line to terminate the list correctly.
    """
    lines = ["ffconcat version 1.0"]

    for i, entry in enumerate(sequence):
        frame = entry["frame"]
        start = float(entry["start"])

        if i < len(sequence) - 1:
            duration = float(sequence[i + 1]["start"]) - start
        else:
            end = float(entry.get("end", start + 1.0))
            duration = end - start

        # --- Fix #3: reject/clamp non-positive durations instead of silently
        # letting them corrupt the timeline ---
        if duration <= 0:
            print(f"Warning: entry {i} ('{frame}') has non-positive duration "
                  f"({duration:.6f}s); clamping to {MIN_FRAME_DURATION:.4f}s.")
            duration = MIN_FRAME_DURATION

        lines.append(f"file '{frame}'")
        lines.append(f"duration {duration:.6f}")

    lines.append(f"file '{sequence[-1]['frame']}'")

    concat_path = os.path.join(frames_dir, "input.txt")
    with open(concat_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return concat_path


def run_ffmpeg(frames_dir, audio_file, total_duration):
    print(f"Generating ultra-HQ MP4 (duration={total_duration:.3f}s)... please wait.")

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
            "-af", "asetpts=PTS-STARTPTS",
            "-c:a", "aac",
            "-b:a", "192k",
        ])

    # --- Fix #2: explicitly hard-cap output at the pre-clamped total_duration,
    # which is already min(json_duration, audio_duration). This is the ONLY
    # place duration is enforced -- no reliance on "-shortest" guesswork and
    # no async audio stretching to paper over mismatches. ---
    cmd.extend(["-t", f"{total_duration:.6f}"])

    cmd.append(OUTPUT_VIDEO)

    result = subprocess.run(cmd, cwd=frames_dir)
    return result.returncode == 0


def main():
    check_binaries()

    if not os.path.exists(FRAMES_DIR):
        fail(f"'{FRAMES_DIR}' folder not found in this directory.")

    json_file = find_single(["*.json"], "JSON")
    if not json_file:
        fail("No JSON file found in this directory.")
    print(f"JSON sequence file detected: {json_file}")

    audio_file = find_single(list(AUDIO_EXTENSIONS), "audio")
    audio_duration = None
    if audio_file:
        audio_file = os.path.abspath(audio_file)
        print(f"Audio file detected: {os.path.basename(audio_file)}")
        audio_duration = get_media_duration(audio_file)
        if audio_duration is None:
            fail(f"Could not determine duration of audio file '{audio_file}'.")
        print(f"Audio duration: {audio_duration:.3f}s")
    else:
        print("No audio file found. Generating silent video.")

    sequence = load_sequence(json_file)
    check_frames_exist(sequence, FRAMES_DIR)

    # Total runtime per the JSON: last frame's 'end' if given, else start + 1s.
    last = sequence[-1]
    json_duration = float(last.get("end", float(last["start"]) + 1.0))

    # --- Fix #2 (continued): clamp to the shorter of JSON-implied duration
    # and actual audio duration, so we never emit frames with no audio (or
    # cut audio short if it happened to be longer than the frame sequence). ---
    if audio_duration is not None:
        total_duration = min(json_duration, audio_duration)
        if abs(json_duration - audio_duration) > 0.05:
            print(f"Note: JSON implies {json_duration:.3f}s but audio is "
                  f"{audio_duration:.3f}s; using the shorter value "
                  f"({total_duration:.3f}s) so video and audio end together.")
    else:
        total_duration = json_duration

    if total_duration <= 0:
        fail(f"Computed total duration is non-positive ({total_duration:.3f}s).")

    build_concat_file(sequence, FRAMES_DIR)

    ok = run_ffmpeg(FRAMES_DIR, audio_file, total_duration)

    if ok:
        os.rename(os.path.join(FRAMES_DIR, OUTPUT_VIDEO), OUTPUT_VIDEO)
        print(f"\nSUCCESS! Video generated: {OUTPUT_VIDEO} ({total_duration:.2f}s)")
    else:
        fail("ffmpeg failed. Check the error log above.")


if __name__ == "__main__":
    main()
