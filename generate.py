import json
import subprocess
import os
import sys
import glob

def main():
    frames_dir = 'frames'

    if not os.path.exists(frames_dir):
        print("Error: Make sure a 'frames' folder exists in this directory.")
        sys.exit(1)

    json_files = glob.glob('*.json')
    if not json_files:
        print("Error: No JSON file found in this directory.")
        sys.exit(1)
        
    json_file = json_files[0]

    audio_file = None
    for ext in ['*.mp3', '*.wav', '*.m4a']:
        found = glob.glob(ext)
        if found:
            audio_file = os.path.abspath(found[0])
            break

    with open(json_file, 'r') as f:
        sequence = json.load(f)

    # Ensure strictly sorted sequence
    sequence.sort(key=lambda x: float(x['start']))

    concat_lines = ["ffconcat version 1.0"]

    # Explicit duration building
    for i, item in enumerate(sequence):
        start = float(item['start'])
        end = float(item['end']) if 'end' in item else (float(sequence[i+1]['start']) if i+1 < len(sequence) else start + 1.0)
        
        duration = max(end - start, 0.033) # Avoid zero or negative durations
        
        concat_lines.append(f"file '{item['frame']}'")
        concat_lines.append(f"duration {duration:.6f}")

    # Concat file rule requires repeating the last file entry at the end
    if sequence:
        concat_lines.append(f"file '{sequence[-1]['frame']}'")

    concat_file_path = os.path.join(frames_dir, 'input.txt')
    with open(concat_file_path, 'w') as f:
        f.write("\n".join(concat_lines) + "\n")

    output_video = "output_hq.mp4"
    
    # Flags to force immediate sync lock
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts", # Regenerate missing timestamps
        "-f", "concat",
        "-safe", "0",
        "-i", "input.txt"
    ]
    
    if audio_file:
        cmd.extend(["-i", audio_file])
        
    cmd.extend([
        "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2", 
        "-c:v", "libx264", 
        "-preset", "slow", 
        "-crf", "15", 
        "-pix_fmt", "yuv420p"
    ])
    
    if audio_file:
        # Use aresample to stretch/fill initial audio padding drift
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "192k",
            "-af", "aresample=async=1:min_hard_comp=0.100000:first_pts=0",
            "-shortest"
        ])

    cmd.append(output_video)

    result = subprocess.run(cmd, cwd=frames_dir)

    if result.returncode == 0:
        os.rename(os.path.join(frames_dir, output_video), output_video)
        print("\nSUCCESS! Video generated with initial sync fixed.")
    else:
        print("\nFAILED. Check FFmpeg error logs above.")

if __name__ == "__main__":
    main()
