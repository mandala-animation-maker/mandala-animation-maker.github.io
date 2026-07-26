# Save this as generate.py
import json
import subprocess
import os
import sys
import glob

def main():
    json_file = 'sequence.json' 
    frames_dir = 'frames' # The folder containing your PNGs

    if not os.path.exists(json_file) or not os.path.exists(frames_dir):
        print("Error: Make sure 'sequence.json' and a 'frames' folder are in this directory.")
        sys.exit(1)

    # 1. Auto-detect an audio file in the folder (.mp3 or .wav)
    audio_file = None
    for ext in ['*.mp3', '*.wav', '*.m4a']:
        found = glob.glob(ext)
        if found:
            audio_file = os.path.abspath(found[0]) # Get absolute path so FFmpeg finds it
            print(f"Audio file detected: {found[0]}")
            break
            
    if not audio_file:
        print("No audio file found (.mp3 or .wav). Generating silent video...")

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
        
        # Padding timeline gaps (holds the frame if there is a gap)
        if start > current_time:
            gap = start - current_time
            if i == 0:
                concat_lines.append(f"file '{frame_name}'")
                concat_lines.append(f"duration {gap:.3f}")
            else:
                prev_frame = sequence[i-1]['frame']
                concat_lines.append(f"file '{prev_frame}'")
                concat_lines.append(f"duration {gap:.3f}")

        # The actual frame duration
        duration = end - start
        concat_lines.append(f"file '{frame_name}'")
        concat_lines.append(f"duration {duration:.3f}")
        current_time = end

    # Required by FFmpeg's concat demuxer
    concat_lines.append(f"file '{sequence[-1]['frame']}'")

    concat_file_path = os.path.join(frames_dir, 'input.txt')
    with open(concat_file_path, 'w') as f:
        f.write("\n".join(concat_lines) + "\n")

    print("Generating ultra-HQ MP4... please wait.")

    output_video = "output_hq.mp4"
    
    # 2. Build the FFmpeg Command
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "input.txt"]
    
    # If audio exists, add it to the command
    if audio_file:
        cmd.extend(["-i", audio_file])
        
    # Add video quality settings
    cmd.extend([
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", 
        "-c:v", "libx264", "-preset", "slow", "-crf", "15", 
        "-pix_fmt", "yuv420p"
    ])
    
    # If audio exists, mix it using high quality AAC encoding
    if audio_file:
        # -shortest ensures the video stops cleanly when the audio stops (or vice versa)
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

    cmd.append(output_video)

    # Run FFmpeg from inside the frames folder
    result = subprocess.run(cmd, cwd=frames_dir)

    if result.returncode == 0:
        # Move the output video to the main folder
        os.rename(os.path.join(frames_dir, output_video), output_video)
        print(f"\nSUCCESS! Video saved as '{output_video}'")
    else:
        print("\nFAILED. Check FFmpeg error logs above.")

if __name__ == "__main__":
    main()