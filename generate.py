#!/usr/bin/env python3
import os
import sys
import json
import glob
import math
import tempfile
import shutil
import subprocess

def find_inputs():
    """Discover the required .mp3 and .json files in the current directory."""
    mp3_files = glob.glob("*.mp3")
    json_files = glob.glob("*.json")

    if len(mp3_files) != 1:
        sys.exit(f"ERROR: Expected exactly one .mp3 file, found {len(mp3_files)}: {mp3_files}")
    if len(json_files) != 1:
        sys.exit(f"ERROR: Expected exactly one .json file, found {len(json_files)}: {json_files}")

    return mp3_files[0], json_files[0]

def validate_frames(segments, frames_dir="frames"):
    """Ensure the frames directory exists and contains every frame referenced in the JSON."""
    if not os.path.isdir(frames_dir):
        sys.exit(f"ERROR: Missing '{frames_dir}/' directory.")

    missing = []
    for seg in segments:
        frame_name = seg.get("frame")
        if not frame_name:
            sys.exit(f"ERROR: Invalid JSON segment, missing 'frame' key: {seg}")
        
        frame_path = os.path.join(frames_dir, frame_name)
        if not os.path.isfile(frame_path):
            missing.append(frame_name)
            
    if missing:
        print("ERROR: The following frames referenced in the JSON are missing from 'frames/':")
        for m in set(missing):
            print(f"  - {m}")
        sys.exit(1)

def get_audio_duration(audio_file):
    """
    Step 1: Get ground-truth audio duration using ffprobe.
    We don't trust the JSON's last 'end' value alone because matching the physical 
    audio bounds ensures no truncation.
    """
    cmd = [
        "ffprobe", 
        "-v", "quiet", 
        "-show_entries", "format=duration", 
        "-of", "csv=p=0", 
        audio_file
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: ffprobe failed to read audio duration.\n{e.stderr}")
    except ValueError:
        sys.exit(f"ERROR: ffprobe returned invalid duration format: {res.stdout}")

def check_ffmpeg_fps_mode_support():
    """
    Check if FFmpeg supports the newer '-fps_mode' or if we must fall back to '-vsync'.
    '-fps_mode' replaced '-vsync' in FFmpeg 5.1.
    """
    try:
        # Run a dummy command that parses arguments without doing actual work
        res = subprocess.run(
            ["ffmpeg", "-fps_mode", "cfr", "-f", "lavfi", "-i", "nullsrc=s=1x1", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True, text=True
        )
        if res.returncode == 0:
            return "-fps_mode"
    except Exception:
        pass
    return "-vsync"

def main():
    audio_file, json_file = find_inputs()
    
    with open(json_file, 'r') as f:
        try:
            segments = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: Failed to parse {json_file}: {e}")

    if not segments:
        sys.exit("ERROR: JSON segments list is empty.")

    validate_frames(segments)
    
    audio_duration = get_audio_duration(audio_file)
    json_duration = segments[-1]["end"]
    
    fps = 30
    frame_duration_sec = 1.0 / fps

    print("--- Video Generation Pre-flight ---")
    print(f"Segments found   : {len(segments)}")
    print(f"Audio duration   : {audio_duration:.3f}s ({audio_duration * 1000:.0f} ms)")
    print(f"JSON end duration: {json_duration:.3f}s ({json_duration * 1000:.0f} ms)")

    if abs(audio_duration - json_duration) > frame_duration_sec:
        print(f"WARNING: Ground-truth audio duration differs from JSON 'end' by more than 1 frame (> {frame_duration_sec:.3f}s). Treating audio as authoritative length.")

    # =========================================================================
    # Step 2: Convert segments to frame counts using CUMULATIVE ROUNDING
    # 
    # Why this fixes the drift bug:
    # Converting each segment's (end - start) to frames independently and rounding 
    # causes rounding errors to accumulate over hundreds of segments. A video 
    # could end up visibly out-of-sync by the end.
    # By rounding the *absolute* timestamp against a cumulative frame counter, 
    # rounding errors self-correct, guaranteeing frame-accurate sync globally.
    # =========================================================================
    cumulative_frames = 0
    frame_sequence = []

    for seg in segments:
        # Calculate the absolute frame boundary from time 0
        target_frame = round(seg["end"] * fps)
        count = target_frame - cumulative_frames
        
        if count > 0:
            frame_sequence.extend([seg["frame"]] * count)
            cumulative_frames = target_frame

    # Pad out the end so the video length >= the real audio length.
    # Why this fixes the audio truncation bug:
    # If the video is even a fraction of a frame shorter than the audio, FFmpeg 
    # may clip the tail end of the audio track. Padding ensures the video holds 
    # the last frame just long enough to let the narration finish naturally.
    required_frames = math.ceil(audio_duration * fps)
    if cumulative_frames < required_frames:
        padding_count = required_frames - cumulative_frames
        frame_sequence.extend([segments[-1]["frame"]] * padding_count)
        cumulative_frames = required_frames
        
    print(f"Computed frames  : {cumulative_frames} frames (at {fps} fps)")

    # =========================================================================
    # Step 3: Materialize a true CFR-friendly image sequence
    #
    # Why this fixes the VFR/Dropped Frames bug:
    # FFmpeg's concat demuxer (using the `duration` directive) generates Variable 
    # Frame Rate (VFR) MP4s when times don't map cleanly to 30fps ticks. Social
    # platforms usually assume CFR uploads, leading to dropped frames/stuttering 
    # after their re-encode. 
    # By materializing strict 1-to-1 frames sequentially and feeding them into 
    # the image2 demuxer, we guarantee a pure, zero-stutter Constant Frame Rate.
    # =========================================================================
    tmp_dir = tempfile.mkdtemp(prefix="video_frames_")
    
    try:
        # Symlink frames to sequence format required by image2 demuxer
        for i, src in enumerate(frame_sequence):
            src_path = os.path.abspath(os.path.join("frames", src))
            dst_path = os.path.join(tmp_dir, f"frame_{i:06d}.png")
            os.symlink(src_path, dst_path)
            
        print(f"Symlinks created : {tmp_dir}/")
        
        fps_flag_name = check_ffmpeg_fps_mode_support()

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(tmp_dir, "frame_%06d.png"),
            "-i", audio_file,
            "-c:v", "libx264",
            "-profile:v", "high",
            "-preset", "medium",
            "-crf", "18",
            # Even width/height & 4:2:0 chroma are required for mobile hardware decoders
            "-pix_fmt", "yuv420p",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-r", str(fps),
            fps_flag_name, "cfr",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            # Moves moov atom to front so Shorts/Reels start streaming instantly
            "-movflags", "+faststart",
            "output_hq.mp4"
        ]

        print(f"\nRunning FFmpeg...\nCommand: {' '.join(cmd)}")
        
        res = subprocess.run(cmd, capture_output=True, text=True)
        
        if res.returncode != 0:
            print("\nFFMPEG ERROR LOG:", file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            sys.exit("ERROR: FFmpeg encoding failed. See stderr above. (Temp directory preserved for inspection)")
            
        print("\nSUCCESS! Video rendered to output_hq.mp4")

    finally:
        # Only cleanup if we succeeded. If it failed, keeping the tmp_dir 
        # is critical for debugging the GitHub Actions runner.
        if 'res' in locals() and res.returncode == 0:
            shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    main()
