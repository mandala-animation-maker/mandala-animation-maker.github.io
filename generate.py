# Save this as generate.py
import json
import subprocess
import os
import sys

def main():
    json_file = 'sequence.json' 
    frames_dir = 'frames' # The folder containing your PNGs

    if not os.path.exists(json_file) or not os.path.exists(frames_dir):
        print("Error: Make sure 'sequence.json' and a 'frames' folder are in this directory.")
        sys.exit(1)

    with open(json_file, 'r') as f:
        sequence = json.load(f)

    # Sort array by start time to be safe
    sequence.sort(key=lambda x: x['start'])

    concat_lines = []
    current_time = 0.0

    for i, item in enumerate(sequence):
        frame_name = item['frame']
        start = item['start']
        end = item['end']
        
        # FIX: Padding timeline gaps
        if start > current_time:
            gap = start - current_time
            if i == 0:
                # Initial start delay: Hold the first frame on screen
                concat_lines.append(f"file '{frame_name}'")
                concat_lines.append(f"duration {gap:.3f}")
            else:
                # Delay between clips: Hold the previous frame
                prev_frame = sequence[i-1]['frame']
                concat_lines.append(f"file '{prev_frame}'")
                concat_lines.append(f"duration {gap:.3f}")

        # The actual frame duration
        duration = end - start
        concat_lines.append(f"file '{frame_name}'")
        concat_lines.append(f"duration {duration:.3f}")
        current_time = end

    # Required by FFmpeg's concat demuxer: repeat the last file without a duration
    concat_lines.append(f"file '{sequence[-1]['frame']}'")

    # Write input.txt to the frames directory
    concat_file_path = os.path.join(frames_dir, 'input.txt')
    with open(concat_file_path, 'w') as f:
        f.write("\n".join(concat_lines) + "\n")

    print("Generating ultra-HQ MP4... please wait.")

    # Execute FFmpeg
    output_video = "output_hq.mp4"
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
        "-i", "input.txt", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", 
        "-c:v", "libx264", "-preset", "slow", "-crf", "15", 
        "-pix_fmt", "yuv420p", output_video
    ]
    
    # Run from within frames folder so relative paths work automatically
    result = subprocess.run(cmd, cwd=frames_dir)

    if result.returncode == 0:
        os.rename(os.path.join(frames_dir, output_video), output_video)
        print(f"\nSUCCESS! Video saved as '{output_video}'")
    else:
        print("\nFAILED. Make sure FFmpeg is installed and added to your system PATH.")

if __name__ == "__main__":
    main()