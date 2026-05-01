# schlangemann-sounds

OpenPeon (CESP v1.0) sound pack built from Schlangemann YouTube clips.

## Setup

```sh
brew install yt-dlp ffmpeg
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Workflow

1. **Add a video URL** to `pack.yaml` under `videos:`.
2. **Download the audio** (one-shot, cached in `.cache/audio/`):
   ```sh
   python build.py --download-only
   ```
3. **Pick clips.** Open `.cache/audio/<video-id>.mp3` in QuickLook / VLC / Audacity, find good moments, note the start/end timestamps (e.g. `0:12.5` to `0:14.2`).
4. **Append clip entries** to the video's `clips:` list in `pack.yaml`:
   ```yaml
   - { start: "0:12.5", end: "0:14.2", category: session.start, file: hallo.mp3, label: "Hallo!" }
   ```
   Categories must come from the CESP standard list (see comments in `pack.yaml`).
5. **Build the pack:**
   ```sh
   python build.py
   ```
   This cuts each clip into `sounds/`, computes sha256, and regenerates `openpeon.json`.

## Install locally for testing

```sh
ln -s "$PWD" ~/.openpeon/packs/schlangemann
```

Then in a Claude Code session: `/peon-ping-use schlangemann`.

## Constraints (from the spec)

- Per-file: **≤ 1 MB**, ideal length **1–5 s**.
- Total: **≤ 50 MB**.
- Filename charset: letters, numbers, `.`, `-`, `_` only.
- `build.py` enforces all of the above.

## Releasing

Tag a version (`git tag v0.1.0 && git push --tags`) and submit to the OpenPeon registry per https://openpeon.com/create.
