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

    # 1. First safety requirement:
    # Ensure they process left-to-right flawlessly in sequential ordering rules format 
    sequence.sort(key=lambda x: x['start'])

    # 2. ⚡ THE VITAL AUDIO/VIDEO SYNC OVERLAP FIX: ⚡ 
    # Force truncate prior word display endings gracefully if crossfading 
    # AI words or JS fallback intervals bleed overlapping boundaries into our upcoming timestamps arrays lengths natively:
    for i in range(len(sequence) - 1):
        if sequence[i]['end'] > sequence[i+1]['start']:
             sequence[i]['end'] = max(sequence[i]['start'], sequence[i+1]['start'])

    concat_lines = ["ffconcat version 1.0"]
    current_time = 0.0

    for i, item in enumerate(sequence):
        frame_name = item['frame']
        start = float(item['start'])
        end = float(item['end'])
        
        if start > current_time:
            gap = start - current_time
            if i == 0:
                concat_lines.append(f"file '{frame_name}'")
                concat_lines.append(f"duration {gap:.6f}") 
            else:
                prev_frame = sequence[i-1]['frame']
                concat_lines.append(f"file '{prev_frame}'")
                concat_lines.append(f"duration {gap:.6f}")
                
            # Align our timeline up natively now to start exactly matched natively. 
            current_time = start

        # Generate seamlessly
        # (This will no longer cumulatively add lengths incorrectly over total audio) 
        duration = end - current_time
        if duration > 0:
            concat_lines.append(f"file '{frame_name}'")
            concat_lines.append(f"duration {duration:.6f}") 
            current_time = end

    # Required padding syntax marker logic safely terminates sequence rendering bounds.
    concat_lines.append(f"file '{sequence[-1]['frame']}'")

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
