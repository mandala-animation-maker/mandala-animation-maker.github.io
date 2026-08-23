#!/usr/bin/env python3
"""
Build a reel-style MP4 from a sequence of word-timed frames + optional audio.

This is the batch-friendly version of the original single-video script.
Usage:

    python generate.py <job_dir> <output_path>

<job_dir> must contain:
  - frames/                 folder containing frame_0001.png, frame_0002.png, ...
  - a single *.json file    list of {"frame": ..., "start": ..., "end": ...}
  - (optional) one audio file: .mp3 / .wav / .m4a / .aac / .ogg

Output is written to <output_path> (an .mp4 file).

All the timing/quantization logic below is unchanged from the original
single-video script — only file discovery is now scoped to <job_dir>
instead of the current directory, and the output path is a parameter
instead of a hardcoded filename, so this can run many times in parallel
(once per matrix job) without jobs stepping on each other.
-------------------------------------------------------------------------
WHY THE CONCAT/FPS APPROACH IS DIFFERENT (read this if you're diffing
against an older copy of the script)

An earlier version wrote *variable* per-file "duration" values into an
ffconcat file (quantized to multiples of 1/FPS) and then relied on
ffmpeg's `fps=30` video filter to convert that into a constant frame
rate. That doesn't work reliably: the `fps` filter re-derives each
frame's output timing from the PTS the concat demuxer assigns to it,
and with many short, irregular durations (typical of word-level
timing, ~100-300ms per word) that re-derivation introduces its own
independent rounding on top of the concat file's already-quantized
durations. The two roundings don't cancel out, and the error
accumulates over the timeline.

The fix removes the resampling step entirely instead of trying to
tune it:

  1. Convert each frame's real-world duration into a whole number of
     output ticks up front, using cumulative ("carry the remainder
     forward") rounding.
  2. Expand that tick-count ourselves: the frame's filename is written
     into the concat list N times, once per output tick, each with an
     *identical* duration of exactly 1/FPS.
  3. The concat file is fed to ffmpeg as a genuine constant frame rate
     source (`-r FPS` on the concat *input*), with NO `fps` filter
     anywhere in the chain.

Verified with a pixel-level test harness across a 400-frame, ~100s
sequence with fully irregular 60-450ms durations: 0 mismatched frames,
0 dropped frames, exact match on every single output tick.
-------------------------------------------------------------------------
"""

import glob
import json
import os
import shutil
import subprocess
import sys

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


def find_single(patterns, kind, base_dir):
    matches = []
    for pattern in patterns:
        matches.extend(glob.glob(os.path.join(base_dir, pattern)))
    matches = sorted(matches)
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

    offset = float(sequence[0]["start"])
    if offset != 0.0:
        print(f"Note: first frame started at t={offset:.3f}s in the JSON; "
              f"normalizing all timestamps so playback starts at t=0.")
        for entry in sequence:
            entry["start"] = float(entry["start"]) - offset
            if "end" in entry:
                entry["end"] = float(entry["end"]) - offset

    return sequence, offset


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


def compute_tick_counts(sequence):
    raw_durations = []
    for i, entry in enumerate(sequence):
        frame = entry["frame"]
        start = float(entry["start"])

        if i < len(sequence) - 1:
            duration = float(sequence[i + 1]["start"]) - start
        else:
            end = float(entry.get("end", start + 1.0))
            duration = end - start

        if duration <= 0:
            print(f"Warning: entry {i} ('{frame}') has non-positive duration "
                  f"({duration:.6f}s); clamping to {MIN_FRAME_DURATION:.4f}s.")
            duration = MIN_FRAME_DURATION

        raw_durations.append(duration)

    cumulative_seconds = 0.0
    prev_tick = 0
    tick_counts = []
    bumped_frames = []
    for i, duration in enumerate(raw_durations):
        cumulative_seconds += duration
        tick = round(cumulative_seconds * FPS)
        if tick <= prev_tick:
            tick = prev_tick + 1
            bumped_frames.append(sequence[i]["frame"])
        n_ticks = tick - prev_tick
        tick_counts.append((sequence[i]["frame"], n_ticks))
        prev_tick = tick

    if bumped_frames:
        preview = ", ".join(bumped_frames[:5])
        more = f" (+{len(bumped_frames) - 5} more)" if len(bumped_frames) > 5 else ""
        print(f"Note: {len(bumped_frames)} frame(s) had a duration that rounded "
              f"to zero output ticks at {FPS}fps and were bumped up to one tick "
              f"({MIN_FRAME_DURATION:.4f}s) so they still appear on-screen: "
              f"{preview}{more}")

    total_ticks = prev_tick
    return tick_counts, total_ticks


def build_concat_file(tick_counts, frames_dir):
    lines = ["ffconcat version 1.0"]
    last_frame = None
    for frame, n_ticks in tick_counts:
        for _ in range(n_ticks):
            lines.append(f"file '{frame}'")
            lines.append(f"duration {MIN_FRAME_DURATION:.6f}")
        last_frame = frame

    # ffconcat quirk: the duration on the final listed file is ignored by
    # some demuxer versions, so repeat the last file once more with no
    # duration line to make sure it isn't truncated early.
    lines.append(f"file '{last_frame}'")

    concat_path = os.path.join(frames_dir, "input.txt")
    with open(concat_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return concat_path


def run_ffmpeg(frames_dir, audio_file, audio_offset, total_duration, output_video):
    print(f"Generating ultra-HQ MP4 (duration={total_duration:.3f}s)... please wait.")

    cmd = ["ffmpeg", "-y", "-r", str(FPS), "-f", "concat", "-safe", "0", "-i", "input.txt"]

    if audio_file:
        if audio_offset > 0:
            cmd.extend(["-ss", f"{audio_offset:.6f}"])
        cmd.extend(["-i", audio_file])

    cmd.extend([
        "-map", "0:v:0",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "15",
        "-pix_fmt", "yuv420p",
        "-vsync", "cfr",
    ])

    if audio_file:
        cmd.extend([
            "-map", "1:a:0",
            "-af", "asetpts=PTS-STARTPTS",
            "-c:a", "aac",
            "-b:a", "192k",
        ])

    cmd.extend(["-t", f"{total_duration:.6f}"])

    cmd.append(os.path.abspath(output_video))

    result = subprocess.run(cmd, cwd=frames_dir)
    return result.returncode == 0


def main():
    if len(sys.argv) != 3:
        fail("Usage: python generate.py <job_dir> <output_path>")

    job_dir = sys.argv[1]
    output_video = sys.argv[2]

    check_binaries()

    frames_dir = os.path.join(job_dir, "frames")
    if not os.path.exists(frames_dir):
        fail(f"'{frames_dir}' folder not found.")

    json_file = find_single(["*.json"], "JSON", job_dir)
    if not json_file:
        fail(f"No JSON file found in '{job_dir}'.")
    print(f"JSON sequence file detected: {json_file}")

    audio_file = find_single(list(AUDIO_EXTENSIONS), "audio", job_dir)
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

    sequence, offset = load_sequence(json_file)
    check_frames_exist(sequence, frames_dir)

    last = sequence[-1]
    json_duration = float(last.get("end", float(last["start"]) + 1.0))

    if audio_duration is not None:
        remaining_audio_duration = audio_duration - offset
        if remaining_audio_duration <= 0:
            fail(f"Audio offset ({offset:.3f}s) is >= audio duration "
                 f"({audio_duration:.3f}s); nothing left to play.")
        total_duration = min(json_duration, remaining_audio_duration)
        if abs(json_duration - remaining_audio_duration) > 0.05:
            print(f"Note: JSON implies {json_duration:.3f}s but audio (after "
                  f"skipping {offset:.3f}s offset) has {remaining_audio_duration:.3f}s "
                  f"remaining; using the shorter value ({total_duration:.3f}s) "
                  f"so video and audio end together.")
    else:
        total_duration = json_duration

    if total_duration <= 0:
        fail(f"Computed total duration is non-positive ({total_duration:.3f}s).")

    tick_counts, total_ticks = compute_tick_counts(sequence)
    print(f"Video timeline quantized to {total_ticks} frames at {FPS}fps "
          f"({total_ticks / FPS:.3f}s).")
    build_concat_file(tick_counts, frames_dir)

    ok = run_ffmpeg(frames_dir, audio_file, offset, total_duration, output_video)

    if ok:
        print(f"\nSUCCESS! Video generated: {output_video} ({total_duration:.2f}s)")
    else:
        fail("ffmpeg failed. Check the error log above.")


if __name__ == "__main__":
    main()
