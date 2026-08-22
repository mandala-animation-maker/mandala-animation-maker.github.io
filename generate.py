import glob
import json
import os
import subprocess
import sys


def main():
  frames_dir = 'frames'

  # 1. Check if the frames folder exists
  if not os.path.exists(frames_dir):
    print("Error: Make sure a 'frames' folder exists in this directory.")
    sys.exit(1)

  # 2. Dynamically search for any JSON file in the directory
  json_files = glob.glob('*.json')
  if not json_files:
    print("Error: No JSON file found in this directory.")
    sys.exit(1)

  json_file = json_files[0]
  print(f"JSON sequence file detected: {json_file}")

  # 3. Dynamically search for audio files
  audio_file = None
  for ext in ['*.mp3', '*.wav', '*.m4a', '*.aac', '*.ogg']:
    found = glob.glob(ext)
    if found:
      audio_file = os.path.abspath(found[0])
      print(f"Audio file detected: {found[0]}")
      break

  if not audio_file:
    print("No audio file found. Generating silent video...")

  with open(json_file, 'r') as f:
    sequence = json.load(f)

  # Sort sequentially by start timestamp
  sequence.sort(key=lambda x: float(x['start']))

  concat_lines = ['ffconcat version 1.0']

  # Calculate frame durations properly
  for i in range(len(sequence)):
    current_frame = sequence[i]['frame']
    current_start = float(sequence[i]['start'])

    if i < len(sequence) - 1:
      next_start = float(sequence[i + 1]['start'])
      duration = max(0.0, next_start - current_start)
      concat_lines.append(f"file '{current_frame}'")
      concat_lines.append(f'duration {duration:.6f}')
    else:
      # Last frame
      concat_lines.append(f"file '{current_frame}'")
      if audio_file:
        concat_lines.append('duration 9999.000000')
      else:
        final_duration = max(
            float(sequence[i].get('end', current_start + 1.0)) - current_start,
            1.0,
        )
        concat_lines.append(f'duration {final_duration:.6f}')
      # Concat demuxer requires repeating the final file entry
      concat_lines.append(f"file '{current_frame}'")

  concat_file_path = os.path.join(frames_dir, 'input.txt')
  with open(concat_file_path, 'w') as f:
    f.write('\n'.join(concat_lines) + '\n')

  print('Generating ultra-HQ MP4... please wait.')
  output_video = 'output_hq.mp4'

  cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'input.txt']

  if audio_file:
    cmd.extend(['-i', audio_file])

  # Video filter: maintain proper framerate and scale to even dimensions
  cmd.extend([
      '-map',
      '0:v:0',
      '-vf',
      'setpts=PTS-STARTPTS,fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2',
      '-c:v',
      'libx264',
      '-preset',
      'slow',
      '-crf',
      '15',
      '-pix_fmt',
      'yuv420p',
  ])

  # Audio filter: hard sync initial offset immediately
  if audio_file:
    cmd.extend([
        '-map',
        '1:a:0',
        '-af',
        'asetpts=PTS-STARTPTS,aresample=async=1000:min_hard_comp=0.1:first_pts=0',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-shortest',
    ])

  cmd.append(output_video)

  result = subprocess.run(cmd, cwd=frames_dir)

  if result.returncode == 0:
    os.rename(os.path.join(frames_dir, output_video), output_video)
    print(
        '\nSUCCESS! Video generated with synchronized initial frames and audio!'
    )
  else:
    print('\nFAILED. Check FFmpeg error logs above.')


if __name__ == '__main__':
  main()
