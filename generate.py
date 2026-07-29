#!/usr/bin/env python3
import os
import sys
import json
import glob
import math
import subprocess
from PIL import Image

def find_inputs():
    mp3_files = glob.glob("*.mp3")
    json_files = glob.glob("*.json")
    if len(mp3_files) != 1: sys.exit(f"ERROR: Expected exactly 1 .mp3, found {len(mp3_files)}")
    if len(json_files) != 1: sys.exit(f"ERROR: Expected exactly 1 .json, found {len(json_files)}")
    return mp3_files[0], json_files[0]

def get_audio_duration(audio_file):
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", audio_file]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        sys.exit(f"ERROR: ffprobe failed to read audio duration.\n{e}")

def main():
    audio_file, json_file = find_inputs()
    frames_dir = "frames"
    fps = 30.0

    with open(json_file, 'r') as f:
        segments = json.load(f)

    if not segments: sys.exit("ERROR: JSON segments list is empty.")

    audio_duration = get_audio_duration(audio_file)
    print(f"Audio Duration: {audio_duration:.3f}s")

    # 1. PREPARE THE FRAME SCHEDULE
    # We figure out exactly how many frames every single image gets.
    schedule = []
    cumulative_frames = 0

    for seg in segments:
        target_frame = round(seg["end"] * fps)
        count = target_frame - cumulative_frames
        if count > 0:
            schedule.append((seg["frame"], count))
            cumulative_frames = target_frame

    # Pad the end to match the exact audio length
    required_frames = math.ceil(audio_duration * fps)
    if cumulative_frames < required_frames:
        padding = required_frames - cumulative_frames
        schedule.append((segments[-1]["frame"], padding))
        cumulative_frames = required_frames

    print(f"Total precise frames to render: {cumulative_frames} frames at {fps} FPS")

    # 2. DETERMINE RESOLUTION FROM THE FIRST IMAGE
    first_frame_path = os.path.join(frames_dir, segments[0]["frame"])
    with Image.open(first_frame_path) as img:
        width, height = img.size
        # Hardware decoders (phones/social media) require EVEN dimensions (divisible by 2)
        width = width if width % 2 == 0 else width - 1
        height = height if height % 2 == 0 else height - 1

    print(f"Video resolution set to: {width}x{height}")

    # 3. SET UP FFMPEG TO RECEIVE RAW PIXELS VIA PIPE
    cmd = [
        "ffmpeg", "-y",
        # Input 1: Raw video from the pipeline (stdin)
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-", 
        # Input 2: The Audio file
        "-i", audio_file,
        # Video encoding settings (Strict CFR)
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        # Audio encoding settings
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        # Output
        "output_hq.mp4"
    ]

    print("Starting FFmpeg render pipe...")
    
    # Open FFmpeg process, exposing its standard input to Python
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # 4. STREAM IMAGES DIRECTLY INTO FFMPEG'S MEMORY
        frames_written = 0
        for frame_name, count in schedule:
            img_path = os.path.join(frames_dir, frame_name)
            
            # Open, force correct size, and convert to raw RGB data
            with Image.open(img_path) as img:
                img = img.convert("RGB")
                if img.size != (width, height):
                    img = img.resize((width, height), Image.Resampling.LANCZOS)
                
                raw_bytes = img.tobytes()

            # Write the exact number of frames required directly to FFmpeg
            for _ in range(count):
                process.stdin.write(raw_bytes)
                frames_written += 1
                
        # Close the pipe, letting FFmpeg know the video is done
        process.stdin.close()
        process.wait()

    except BrokenPipeError:
        # If FFmpeg crashed early, it will close the pipe
        pass

    if process.returncode != 0:
        stderr_output = process.stderr.read().decode('utf-8')
        sys.exit(f"\nFFMPEG ERROR:\n{stderr_output}")

    print(f"\nSUCCESS! Rendered exactly {frames_written} frames to output_hq.mp4")

if __name__ == "__main__":
    main()
