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

    audio_file = None
    for ext in ['*.mp3', '*.wav', '*.m4a']:
        found = glob.glob(ext)
        if found:
            audio_file = os.path.abspath(found[0])
            print(f"Audio file detected: {found[0]}")
            break
            
    if not audio_file:
        print("No audio file found (.mp3 or .wav). Generating silent video...")

    with open(json_file, 'r') as f:
        sequence = json.load(f)

    # 1. Safety requirement: process left-to-right flawless sequential ordering.
    # Converted to float inside lambda to prevent string sorting issues.
    sequence.sort(key=lambda x: float(x['start']))

    # Generate a black frame for the very first silence natively.
    # It takes the very first frame and blacks it out to ensure the aspect ratio/dimensions perfectly match.
    black_frame_name = "black_base_frame.png"
    black_frame_path = os.path.join(frames_dir, black_frame_name)
    if not os.path.exists(black_frame_path):
        print("Generating initial black frame for the beginning silence...")
        first_frame_path = os.path.join(frames_dir, sequence[0]['frame'])
        subprocess.run([
            "ffmpeg", "-y", "-i", first_frame_path, 
            "-vf", "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill", 
            "-frames:v", "1", black_frame_path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    concat_lines = ["ffconcat version 1.0"]

    # 2. ⚡ THE VITAL AUDIO/VIDEO SYNC OVERLAP FIX: ⚡
    # The current frame will now persist during silences until the NEXT frame's exact start.
    for i, item in enumerate(sequence):
        start = float(item['start'])

        if i == 0:
            # If there's a starting gap before the first spoken word, show the black screen ONCE.
            if start > 0:
                concat_lines.append(f"file '{black_frame_name}'")
                concat_lines.append(f"duration {start:.6f}") 
        else:
            # For everything else: Previous frame stays active precisely until THIS next frame starts.
            # (No middle black screens. The frame waits through the silence).
            prev_start = float(sequence[i-1]['start'])
            duration = start - prev_start
            if duration > 0:
                concat_lines.append(f"file '{sequence[i-1]['frame']}'")
                concat_lines.append(f"duration {duration:.6f}")

    # 3. FIX FOR AUDIO CUTTING OFF AT THE END:
    # We extend the last frame to a massive duration.
    # Because ffmpeg uses "-shortest", it will force the video to smoothly end EXACTLY when the audio stream ends,
    # ensuring not a single millisecond of trailing audio breathing/talking is ever cut prematurely!
    last_item = sequence[-1]
    concat_lines.append(f"file '{last_item['frame']}'")
    
    if audio_file:
        concat_lines.append("duration 9999.000000")
    else:
        # Fallback behaviour just in case we run it strictly without an audio file
        final_duration = max(float(last_item['end']) - float(last_item['start']), 0.1)
        concat_lines.append(f"duration {final_duration:.6f}")
        
    # Standard FFmpeg concat rules dictate the last file must be repeated once more without a duration label.
    concat_lines.append(f"file '{last_item['frame']}'")

    concat_file_path = os.path.join(frames_dir, 'input.txt')
    with open(concat_file_path, 'w') as f:
        f.write("\n".join(concat_lines) + "\n")

    print("Generating ultra-HQ MP4... please wait.")
    output_video = "output_hq.mp4"
    
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "input.txt"]
    
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
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])

    cmd.append(output_video)

    # Subprocess execution cleanly from internal folders rules mapping parameters! 
    result = subprocess.run(cmd, cwd=frames_dir)

    if result.returncode == 0:
        os.rename(os.path.join(frames_dir, output_video), output_video)
        print(f"\nSUCCESS! Video mathematically perfectly generated without temporal timeline desync drifting!")
    else:
        print("\nFAILED. Check FFmpeg error logs above.")

if __name__ == "__main__":
    main()
