import json
import subprocess
import os
import sys
import glob
import math

# Strict 30 FPS for flawless social media compatibility (TikTok, IG, YouTube, Facebook)
FPS = 30.0 

def get_audio_duration(audio_file):
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_file
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except:
        return None

def main():
    frames_dir = 'frames'

    # --- 1. Basic Checks ---
    if not os.path.exists(frames_dir):
        print("Error: Make sure a 'frames' folder exists in this directory.")
        sys.exit(1)

    json_files = glob.glob('*.json')
    if not json_files:
        print("Error: No JSON sequence file found.")
        sys.exit(1)
        
    json_file = json_files[0]
    print(f"[+] Loaded sequence: {json_file}")

    audio_file = None
    for ext in ['*.mp3', '*.wav', '*.m4a']:
        found = glob.glob(ext)
        if found:
            audio_file = os.path.abspath(found[0])
            print(f"[+] Loaded audio:    {os.path.basename(audio_file)}")
            break

    # --- 2. Load Sequence ---
    with open(json_file, 'r') as f:
        sequence = json.load(f)

    # Sort strictly by start time
    sequence.sort(key=lambda x: float(x['start']))

    # Generate an opening black frame in case the JSON doesn't start at 0.0s
    black_frame = os.path.join(frames_dir, "black_base_frame.png")
    if not os.path.exists(black_frame):
        print("[+] Creating base black frame...")
        first_img = os.path.join(frames_dir, sequence[0]['frame'])
        subprocess.run([
            "ffmpeg", "-y", "-i", first_img, 
            "-vf", "drawbox=color=black:t=fill", 
            "-frames:v", "1", black_frame
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- 3. Determine Total Timeline Length ---
    last_item_start = float(sequence[-1]['start'])
    last_item_end = float(sequence[-1].get('end', last_item_start + 1.0))
    
    audio_duration = get_audio_duration(audio_file) if audio_file else 0.0
    total_duration = max(audio_duration, last_item_end)
    
    total_frames = math.ceil(total_duration * FPS)

    # --- 4. Absolute Time Mapping (The Magic Fix) ---
    # We map every JSON entry to its exact 30FPS slot. No timing drift!
    events = []
    if float(sequence[0]['start']) > 0:
        events.append({'frame': black_frame, 'start_frame': 0})
        
    for item in sequence:
        start_time = float(item['start'])
        # Round to nearest 30fps slot
        slot = int(round(start_time * FPS))
        events.append({
            'frame': os.path.join(frames_dir, item['frame']), 
            'start_slot': slot
        })

    # Sort events by slot just to be absolutely safe
    events.sort(key=lambda x: x['start_slot'])

    # --- 5. Stream Video to FFmpeg ---
    print(f"\n[>>>] Compiling {total_frames} frames into a 30 FPS Social Media MP4...")
    output_video = "output_social.mp4"
    
    cmd = [
        "ffmpeg", "-y", 
        "-f", "image2pipe", 
        "-vcodec", "png", 
        "-framerate", str(int(FPS)), 
        "-i", "-"
    ]
    
    if audio_file:
        cmd.extend(["-i", audio_file])
        
    # Standard social media encoding parameters (H.264, YUV420p)
    cmd.extend([
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", 
        "-c:v", "libx264", 
        "-preset", "fast", 
        "-crf", "18", 
        "-pix_fmt", "yuv420p"
    ])
    
    if audio_file:
        cmd.extend(["-c:a", "aac", "-b:a", "256k", "-shortest"])

    cmd.append(output_video)

    process = subprocess.Popen(
        cmd, 
        stdin=subprocess.PIPE, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL, 
        cwd=frames_dir
    )
    
    current_event_idx = 0
    current_frame_path = None
    current_frame_bytes = b""
    
    try:
        # The Flipbook Loop
        for frame_slot in range(total_frames):
            
            # Check if it is time to move to the next image based on the absolute slot
            while current_event_idx < len(events) - 1 and frame_slot >= events[current_event_idx + 1]['start_slot']:
                current_event_idx += 1
                
            frame_path = events[current_event_idx]['frame']
            
            # Only read from disk when the image actually changes
            if frame_path != current_frame_path:
                if os.path.exists(frame_path):
                    with open(frame_path, 'rb') as f:
                        current_frame_bytes = f.read()
                else:
                    # If image is missing, it just continues showing the last one (no freezing!)
                    print(f"\n[!] Missing image: {frame_path}")
                current_frame_path = frame_path
                
            # Drop the image into the 1/30th second slot
            if current_frame_bytes:
                process.stdin.write(current_frame_bytes)
            
            # Progress UI
            if frame_slot % 15 == 0:
                percent = int((frame_slot / total_frames) * 100)
                sys.stdout.write(f"\r[>] Rendering: {percent}% complete ({frame_slot}/{total_frames} frames)...")
                sys.stdout.flush()
                
        # Close pipe to tell FFmpeg to finish saving
        process.stdin.close()
        process.wait()
        
        if process.returncode == 0:
            final_path = os.path.join(frames_dir, output_video)
            if os.path.exists(final_path):
                os.rename(final_path, output_video)
            print(f"\n\n[SUCCESS] Video created perfectly: '{output_video}'")
        else:
            print("\n\n[ERROR] FFmpeg crashed. Remove stdout/stderr suppression to see why.")
            
    except Exception as e:
        print(f"\n\n[FATAL ERROR] {e}")
        process.kill()

if __name__ == "__main__":
    main()
