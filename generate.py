import glob
import json
import os
import subprocess
import sys


def find_file_by_extension(ext):
  """Finds the first file matching the extension in root or subdirectories."""
  files = glob.glob(f"*.{ext}")
  if not files:
    files = glob.glob(f"**/*.{ext}", recursive=True)
  return files[0] if files else None


def resolve_frame_path(frame_name):
  """Resolves the path to the frame image either directly or inside 'frames/'."""
  if os.path.exists(frame_name):
    return os.path.abspath(frame_name)

  # Look inside the 'frames' directory
  in_frames = os.path.join("frames", os.path.basename(frame_name))
  if os.path.exists(in_frames):
    return os.path.abspath(in_frames)

  # Fallback to given path string
  return os.path.abspath(frame_name)


def main():
  # 1. Locate the JSON timing file
  json_path = find_file_by_extension("json")
  if not json_path:
    print("Error: No JSON file found in root or subfolders!")
    sys.exit(1)
  print(f"--> Found JSON data file: {json_path}")

  # 2. Locate the MP3 audio file
  mp3_path = find_file_by_extension("mp3")
  if mp3_path:
    print(f"--> Found MP3 audio file: {mp3_path}")
  else:
    print("--> Warning: No MP3 audio file found. Generating silent video.")

  # 3. Read frame timing data
  with open(json_path, "r", encoding="utf-8") as f:
    frame_data = json.load(f)

  if not isinstance(frame_data, list) or not frame_data:
    print("Error: JSON file must contain a non-empty array of frame entries!")
    sys.exit(1)

  # Sort timing entries chronologically by start time
  frame_data.sort(key=lambda x: x.get("start", 0))

  # 4. Generate FFmpeg concat manifest
  concat_file = "concat_list.txt"
  total_duration = 0

  with open(concat_file, "w", encoding="utf-8") as f:
    for item in frame_data:
      frame_file = item["frame"]
      start = item["start"]
      end = item["end"]
      duration = max(0, end - start)
      total_duration = max(total_duration, end)

      img_path = resolve_frame_path(frame_file)
      if not os.path.exists(img_path):
        print(f"Warning: Could not locate frame image at: {img_path}")

      # Format path safely for FFmpeg
      safe_path = img_path.replace("'", "'\\''")
      f.write(f"file '{safe_path}'\n")
      f.write(f"duration {duration:.6f}\n")

    # FFmpeg concat demuxer requires repeating the last file entry
    last_img_path = resolve_frame_path(frame_data[-1]["frame"])
    safe_path = last_img_path.replace("'", "'\\''")
    f.write(f"file '{safe_path}'\n")

  print(
      f"--> Calculated {len(frame_data)} keyframes across {total_duration:.2f}"
      " seconds."
  )

  # 5. Build FFmpeg command for strict 30 FPS rendering
  output_video = "output_hq.mp4"
  cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file]

  if mp3_path:
    cmd.extend(["-i", mp3_path])

  # Video flags:
  # -vf "fps=30,format=yuv420p": Converts dynamic timings into a strict 30 FPS Constant Frame Rate (CFR)
  # -c:v libx264 -crf 18: High quality H.264 video encoding
  cmd.extend([
      "-vf",
      "fps=30,format=yuv420p",
      "-c:v",
      "libx264",
      "-preset",
      "medium",
      "-crf",
      "18",
      "-r",
      "30",
  ])

  if mp3_path:
    cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

  cmd.append(output_video)

  # 6. Run FFmpeg command
  print("--> Rendering final MP4 video...")
  try:
    subprocess.run(cmd, check=True)
    print(f"--> Render complete! File saved as {output_video}")
  except subprocess.CalledProcessError as e:
    print(f"Error during video generation: {e}")
    sys.exit(1)
  finally:
    # Clean up temporary manifest
    if os.path.exists(concat_file):
      os.remove(concat_file)


if __name__ == "__main__":
  main()
