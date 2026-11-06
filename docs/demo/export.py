"""Export the captured walkthrough frames with FFmpeg (no third-party Python packages)."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DURATIONS = [8, 10, 10, 10, 10, 10, 8]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    args = parser.parse_args()
    frames = ROOT / 'output' / 'playwright'
    media = ROOT / 'docs' / 'media'
    for i in range(len(DURATIONS)):
        if not (frames / f'relay-scene-{i}.png').is_file():
            parser.error('Capture frames first; see docs/demo/README.md')
    playlist = frames / 'relay-video.ffconcat'
    lines = ['ffconcat version 1.0']
    for i, duration in enumerate(DURATIONS):
        lines.extend([f"file 'relay-scene-{i}.png'", f'duration {duration}'])
    lines.append("file 'relay-scene-6.png'")
    playlist.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    subprocess.run([
        args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
        '-f', 'concat', '-safe', '0', '-i', str(playlist),
        '-vf', 'fps=24,format=yuv420p', '-t', str(sum(DURATIONS)),
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
        '-movflags', '+faststart', '-an',
        str(media / 'agent-relay-walkthrough.mp4'),
    ], check=True)
    shutil.copyfile(frames / 'relay-scene-0.png', media / 'agent-relay-poster.png')
    print('Exported 66-second walkthrough and poster to docs/media')


if __name__ == '__main__':
    main()
