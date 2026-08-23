#!/usr/bin/env python3
"""
Scan the extracted upload for job folders and emit a JSON array of job
names, for use as a GitHub Actions matrix.

Expected layout after unzip (folder names/prefix are flexible, see below):

  jobs/
    job_0001/
      frames/frame_0001.png, frame_0002.png, ...
      <something>.json
      <something>.mp3 (optional)
    job_0002/
      ...
    ...

A "job folder" = any immediate subdirectory of jobs/ that contains a
'frames' subfolder and at least one .json file. Anything that doesn't
match that shape is skipped with a warning, so a stray file or an
incorrectly-zipped folder won't break the whole batch.
"""

import glob
import json
import os
import sys

JOBS_ROOT = "jobs"


def main():
    if not os.path.isdir(JOBS_ROOT):
        print(f"Error: '{JOBS_ROOT}' directory not found after extraction.", file=sys.stderr)
        sys.exit(1)

    candidates = sorted(
        d for d in os.listdir(JOBS_ROOT)
        if os.path.isdir(os.path.join(JOBS_ROOT, d))
    )

    valid_jobs = []
    for name in candidates:
        job_path = os.path.join(JOBS_ROOT, name)
        frames_dir = os.path.join(job_path, "frames")
        json_files = glob.glob(os.path.join(job_path, "*.json"))

        if not os.path.isdir(frames_dir):
            print(f"Warning: skipping '{name}' — no 'frames' subfolder found.", file=sys.stderr)
            continue
        if not json_files:
            print(f"Warning: skipping '{name}' — no .json timing file found.", file=sys.stderr)
            continue
        png_count = len(glob.glob(os.path.join(frames_dir, "*.png")))
        if png_count == 0:
            print(f"Warning: skipping '{name}' — 'frames' folder has no .png files.", file=sys.stderr)
            continue

        valid_jobs.append(name)

    if not valid_jobs:
        print("Error: no valid job folders found under 'jobs/'. "
              "Each job needs jobs/<name>/frames/*.png and jobs/<name>/*.json.", file=sys.stderr)
        sys.exit(1)

    print(f"Discovered {len(valid_jobs)} valid job(s): {valid_jobs}", file=sys.stderr)

    # This is the only thing written to stdout — GitHub Actions will
    # capture it as the matrix value.
    print(json.dumps(valid_jobs))


if __name__ == "__main__":
    main()
