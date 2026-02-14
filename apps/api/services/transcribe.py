"""Local transcription using faster-whisper with word-level timestamps."""

import logging
import subprocess
import json
import numpy as np
from pathlib import Path

from apps.api.config import WHISPER_MODEL

logger = logging.getLogger(__name__)


def get_audio_energy(audio_path: str, sr: int = 16000) -> dict:
    """Compute audio energy curve and detect silences/emphasis moments."""
    try:
        # Use ffmpeg to extract raw audio
        cmd = [
            "ffmpeg", "-i", audio_path, "-ac", "1", "-ar", str(sr),
            "-f", "f32le", "-vn", "pipe:1"
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            logger.warning("FFmpeg audio extraction failed, using empty analysis")
            return {"silences": [], "emphasis_moments": [], "energy_curve": []}

        audio_data = np.frombuffer(result.stdout, dtype=np.float32)
        if len(audio_data) == 0:
            return {"silences": [], "emphasis_moments": [], "energy_curve": []}

        # Compute energy in windows
        window_size = int(sr * 0.05)  # 50ms windows
        hop_size = int(sr * 0.025)    # 25ms hop
        energy = []
        for i in range(0, len(audio_data) - window_size, hop_size):
            window = audio_data[i:i + window_size]
            rms = float(np.sqrt(np.mean(window ** 2)))
            energy.append(rms)

        if not energy:
            return {"silences": [], "emphasis_moments": [], "energy_curve": []}

        energy_arr = np.array(energy)
        mean_energy = float(np.mean(energy_arr))
        silence_threshold = mean_energy * 0.1
        emphasis_threshold = mean_energy * 2.0

        # Detect silences (consecutive low-energy windows)
        silences = []
        in_silence = False
        silence_start = 0.0
        for i, e in enumerate(energy):
            time_sec = i * 0.025
            if e < silence_threshold:
                if not in_silence:
                    in_silence = True
                    silence_start = time_sec
            else:
                if in_silence:
                    duration = time_sec - silence_start
                    if duration > 0.3:  # Only count silences > 300ms
                        silences.append({
                            "start": round(silence_start, 3),
                            "end": round(time_sec, 3),
                            "duration": round(duration, 3),
                        })
                    in_silence = False

        # Detect emphasis moments (high energy peaks)
        emphasis_moments = []
        for i, e in enumerate(energy):
            time_sec = i * 0.025
            if e > emphasis_threshold:
                if not emphasis_moments or time_sec - emphasis_moments[-1]["time"] > 0.5:
                    emphasis_moments.append({
                        "time": round(time_sec, 3),
                        "strength": round(float(e / mean_energy), 2),
                    })

        # Downsample energy curve for storage
        step = max(1, len(energy) // 200)
        energy_curve = [round(float(e), 4) for e in energy[::step]]

        return {
            "silences": silences,
            "emphasis_moments": emphasis_moments,
            "energy_curve": energy_curve,
        }
    except Exception as e:
        logger.error(f"Audio energy analysis failed: {e}")
        return {"silences": [], "emphasis_moments": [], "energy_curve": []}


def transcribe_video(video_path: str) -> dict:
    """Transcribe a video file using faster-whisper with word-level timestamps.

    Returns dict with:
      - text: full transcript text
      - segments: list of segment dicts with word-level timestamps
      - language: detected language
    """
    try:
        from faster_whisper import WhisperModel

        logger.info(f"Loading faster-whisper model: {WHISPER_MODEL}")
        model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")

        logger.info(f"Transcribing: {video_path}")
        segments_gen, info = model.transcribe(
            video_path,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )

        segments = []
        full_text = []

        for segment in segments_gen:
            words = []
            if segment.words:
                for w in segment.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "probability": round(w.probability, 3),
                    })

            seg_data = {
                "id": segment.id,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
                "words": words,
            }
            segments.append(seg_data)
            full_text.append(segment.text.strip())

        transcript = {
            "text": " ".join(full_text),
            "segments": segments,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
        }

        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"language={info.language}"
        )
        return transcript

    except ImportError:
        logger.warning("faster-whisper not available, using demo transcript")
        return _demo_transcript(video_path)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return _demo_transcript(video_path)


def _demo_transcript(video_path: str) -> dict:
    """Generate a simple demo transcript when Whisper is not available."""
    # Get video duration via ffprobe
    duration = 30.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", video_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            duration = float(info.get("format", {}).get("duration", 30.0))
    except Exception:
        pass

    return {
        "text": "This is a demo transcript for testing purposes. "
                "The actual transcription requires faster-whisper to be installed.",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": min(5.0, duration),
                "text": "This is a demo transcript for testing purposes.",
                "words": [
                    {"word": "This", "start": 0.0, "end": 0.5, "probability": 0.99},
                    {"word": "is", "start": 0.5, "end": 0.7, "probability": 0.99},
                    {"word": "a", "start": 0.7, "end": 0.8, "probability": 0.99},
                    {"word": "demo", "start": 0.8, "end": 1.2, "probability": 0.99},
                    {"word": "transcript", "start": 1.2, "end": 1.8, "probability": 0.99},
                    {"word": "for", "start": 1.8, "end": 2.0, "probability": 0.99},
                    {"word": "testing", "start": 2.0, "end": 2.5, "probability": 0.99},
                    {"word": "purposes", "start": 2.5, "end": 3.2, "probability": 0.99},
                ],
            },
            {
                "id": 1,
                "start": 5.0,
                "end": min(10.0, duration),
                "text": "The actual transcription requires faster-whisper.",
                "words": [
                    {"word": "The", "start": 5.0, "end": 5.3, "probability": 0.99},
                    {"word": "actual", "start": 5.3, "end": 5.7, "probability": 0.99},
                    {"word": "transcription", "start": 5.7, "end": 6.5, "probability": 0.99},
                    {"word": "requires", "start": 6.5, "end": 7.0, "probability": 0.99},
                    {"word": "faster-whisper", "start": 7.0, "end": 8.0, "probability": 0.99},
                ],
            },
        ],
        "language": "en",
        "language_probability": 0.99,
    }


def analyze_video(video_path: str) -> dict:
    """Run full analysis: transcription + audio energy."""
    transcript = transcribe_video(video_path)
    energy_analysis = get_audio_energy(video_path)

    return {
        "transcript": transcript,
        "analysis": energy_analysis,
    }
