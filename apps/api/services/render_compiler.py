"""Render compiler: converts EditPlan -> deterministic FFmpeg commands."""

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from apps.api.config import MUSIC_DIR, MAX_RENDER_TIMEOUT_SEC
from apps.api.models.schemas import EditPlan

logger = logging.getLogger(__name__)

# Maximum chars of FFmpeg stderr to include in error messages
_MAX_STDERR_CHARS = 2000

def _run_ffmpeg(cmd: list[str], step_name: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run an FFmpeg command with proper error capture.

    Raises RuntimeError with the last ~2k chars of stderr on failure.
    """
    logger.info(f"FFmpeg [{step_name}]: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        stderr_tail = stderr_text[-_MAX_STDERR_CHARS:] if len(stderr_text) > _MAX_STDERR_CHARS else stderr_text
        logger.error(f"FFmpeg [{step_name}] failed (rc={result.returncode}):\n{stderr_tail}")
        raise RuntimeError(
            f"FFmpeg {step_name} failed: {stderr_tail.strip()[-500:]}"
        )
    return result

def generate_ass_subtitles(
    transcript: dict,
    edit_plan: EditPlan,
    output_path: str,
) -> str:
    """Generate ASS subtitle file from transcript aligned to the edit plan timeline."""
    caption_cfg = edit_plan.captions
    if not caption_cfg.enabled:
        return ""

    # Map original timestamps to final timeline timestamps
    timeline_map = _build_timeline_map(edit_plan)

    # Get style params
    style_presets = {
        "snappy": {"fontsize": 58, "outline": 3, "shadow": 2, "bold": 1},
        "cinematic": {"fontsize": 48, "outline": 2, "shadow": 3, "bold": 0},
        "podcast": {"fontsize": 52, "outline": 2, "shadow": 1, "bold": 0},
        "luxury": {"fontsize": 44, "outline": 1, "shadow": 2, "bold": 0},
        "study": {"fontsize": 50, "outline": 2, "shadow": 1, "bold": 0},
        "default": {"fontsize": 52, "outline": 2, "shadow": 2, "bold": 0},
    }
    style = style_presets.get(caption_cfg.style_id, style_presets["default"])

    ass_content = f"""[Script Info]
Title: Compose Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,{style['fontsize']},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},2,40,40,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Group words into caption chunks
    all_words = []
    for seg in transcript.get("segments", []):
        for word in seg.get("words", []):
            all_words.append(word)

    if not all_words:
        # Fallback: use segment-level timing
        for seg in transcript.get("segments", []):
            mapped_start = _map_time(seg["start"], timeline_map)
            mapped_end = _map_time(seg["end"], timeline_map)
            if mapped_start is not None and mapped_end is not None:
                start_str = _format_ass_time(mapped_start)
                end_str = _format_ass_time(mapped_end)
                text = seg["text"].replace("\n", "\\N")
                ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"
        Path(output_path).write_text(ass_content)
        return output_path

    # Chunk words into groups
    max_words = caption_cfg.max_words_per_line * caption_cfg.max_lines
    chunks = []
    current_chunk = []

    for word in all_words:
        current_chunk.append(word)
        if len(current_chunk) >= max_words:
            chunks.append(current_chunk)
            current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    for chunk in chunks:
        orig_start = chunk[0]["start"]
        orig_end = chunk[-1]["end"]
        mapped_start = _map_time(orig_start, timeline_map)
        mapped_end = _map_time(orig_end, timeline_map)

        if mapped_start is None or mapped_end is None:
            continue

        # Build text with line breaks
        words_text = [w["word"] for w in chunk]
        lines = []
        line_words = []
        for wt in words_text:
            line_words.append(wt)
            if len(line_words) >= caption_cfg.max_words_per_line:
                lines.append(" ".join(line_words))
                line_words = []
        if line_words:
            lines.append(" ".join(line_words))

        text = "\\N".join(lines[:caption_cfg.max_lines])
        start_str = _format_ass_time(mapped_start)
        end_str = _format_ass_time(mapped_end)
        ass_content += f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}\n"

    Path(output_path).write_text(ass_content)
    logger.info(f"ASS subtitles generated: {len(chunks)} chunks -> {output_path}")
    return output_path

def _build_timeline_map(edit_plan: EditPlan) -> list[dict]:
    """Build a mapping from original video time to final timeline time."""
    timeline = []
    offset = 0.0
    for cut in edit_plan.main_cuts:
        timeline.append({
            "orig_start": cut.start,
            "orig_end": cut.end,
            "final_start": offset,
            "final_end": offset + (cut.end - cut.start),
        })
        offset += cut.end - cut.start
    return timeline

def _map_time(orig_time: float, timeline_map: list[dict]) -> float | None:
    """Map an original video timestamp to the final timeline."""
    for entry in timeline_map:
        if entry["orig_start"] <= orig_time <= entry["orig_end"]:
            offset_in_cut = orig_time - entry["orig_start"]
            return entry["final_start"] + offset_in_cut
    return None

def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp (H:MM:SS.CC)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def compile_render(
    edit_plan: EditPlan,
    source_video: str,
    transcript: dict,
    output_path: str,
    work_dir: str | None = None,
) -> str:
    """Compile and execute the FFmpeg render pipeline.

    Returns the path to the output video.
    """
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="compose_render_")
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting render: {len(edit_plan.main_cuts)} cuts, output -> {output_path}")

    # Aspect handling:
    # - "fit": preserve aspect ratio and pad (no stretch, no crop) ✅ default
    # - "fill": preserve aspect ratio and crop to fill 9:16 (no stretch, but crops edges)
    fit_mode = "fit"  # later wire this to UI/preset

    if fit_mode == "fill":
        vf_base = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    else:
        vf_base = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"

    # Step 1: Cut and concatenate main segments
    segments_list_path = work / "segments.txt"
    segment_paths = []
    failed_segments = []

    for i, cut in enumerate(edit_plan.main_cuts):
        seg_path = work / f"seg_{i:03d}.mp4"
        duration = cut.end - cut.start

        # Check if this segment needs punch-in
        punch_in = None
        for pi in edit_plan.punch_ins:
            if pi.start >= cut.start and pi.end <= cut.end:
                punch_in = pi
                break

        if punch_in:
            scale = punch_in.scale

            if fit_mode == "fill":
                vf = (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,"
                    f"zoompan=z={scale}:d=1:s=1080x1920"
                )
            else:
                vf = (
                    "scale=1080:1920:force_original_aspect_ratio=decrease,"
                    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                    f"zoompan=z={scale}:d=1:s=1080x1920"
                )

            cmd = [
                "ffmpeg", "-y",
                "-i", source_video,
                "-ss", str(cut.start), "-t", str(duration),
                "-vf", f"{vf_base},scale=iw*{scale}:ih*{scale},crop=1080:1920",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "2",
                "-af", "aresample=async=1:first_pts=0",
                "-c:a", "aac", "-b:a", "160k",
                str(seg_path),
            ]
        else:
            # Simple trim - ensure 9:16 output
            cmd = [
                "ffmpeg", "-y",
                "-i", source_video,
                "-ss", str(cut.start), "-t", str(duration),
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "2",
                "-af", "aresample=async=1:first_pts=0",
                "-c:a", "aac", "-b:a", "160k",
                str(seg_path),
            ]

        logger.info(f"Cutting segment {i}: {cut.start:.2f}-{cut.end:.2f}")
        try:
            _run_ffmpeg(cmd, f"segment-{i}", timeout=180)
            if seg_path.exists() and seg_path.stat().st_size > 0:
                segment_paths.append(seg_path)
            else:
                failed_segments.append(i)
                logger.warning(f"Segment {i} produced empty output")
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            failed_segments.append(i)
            logger.warning(f"Segment {i} cut failed (non-fatal, skipping): {e}")

    if not segment_paths:
        raise RuntimeError(
            f"No segments created successfully ({len(failed_segments)} failed). "
            f"The source video may be corrupted or in an unsupported format."
        )

    if failed_segments:
        logger.warning(f"{len(failed_segments)} of {len(edit_plan.main_cuts)} segments failed: {failed_segments}")

    # Step 2: Handle b-roll inserts (placeholder, currently not stitched here)
    broll_segments = {}
    if edit_plan.broll.enabled and edit_plan.broll.inserts:
        for bi in edit_plan.broll.inserts:
            if bi.asset_path and Path(bi.asset_path).exists():
                broll_segments[bi.start] = {
                    "path": bi.asset_path,
                    "start": bi.start,
                    "end": bi.end,
                }

    # Step 3: Build concat list
    with open(segments_list_path, "w") as f:
        for sp in segment_paths:
            f.write(f"file '{sp}'\n")

    concat_path = work / "concat.mp4"
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(segments_list_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-c:a", "aac", "-b:a", "160k",
            str(concat_path),
        ],
        "concat",
        timeout=180,
    )

    # Step 4: Overlay b-roll and burn captions
    current_video = str(concat_path)

    # Collect valid b-roll clips sorted by start time
    broll_clips = sorted(broll_segments.values(), key=lambda b: b["start"]) if broll_segments else []

    has_captions = False
    ass_path = str(work / "captions.ass")
    if edit_plan.captions.enabled:
        generate_ass_subtitles(transcript, edit_plan, ass_path)
        has_captions = Path(ass_path).exists() and Path(ass_path).stat().st_size > 100

    if broll_clips:
        # Build overlay filter with optional caption burn in a single pass
        overlay_path = work / "overlay.mp4"
        inputs = ["-i", current_video]
        for bc in broll_clips:
            inputs.extend(["-i", bc["path"]])

        filters = []
        last_label = "0:v"
        for idx, bc in enumerate(broll_clips):
            broll_idx = idx + 1
            prep = f"br{idx}"
            out = f"v{idx}"
            dur = bc["end"] - bc["start"]

            filters.append(
                f"[{broll_idx}:v]trim=duration={dur:.3f},"
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,"
                f"setpts=PTS-STARTPTS+{bc['start']:.3f}/TB,"
                f"tpad=stop_mode=clone:stop_duration={dur:.3f}[{prep}]"
            )
            filters.append(
                f"[{last_label}][{prep}]overlay="
                f"enable='between(t,{bc['start']:.3f},{bc['end']:.3f})'[{out}]"
            )
            last_label = out

        if has_captions:
            cap_out = "vcap"
            filters.append(f"[{last_label}]ass={ass_path}[{cap_out}]")
            last_label = cap_out

        cmd = ["ffmpeg", "-y"] + inputs + [
            "-filter_complex_threads", "1",
            "-filter_complex", ";".join(filters),
            "-map", f"[{last_label}]", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "2",
            "-c:a", "copy",
            str(overlay_path),
        ]
        
        logger.info(f"B-roll overlay: {len(broll_clips)} clips" + (" + captions" if has_captions else ""))
        try:
            _run_ffmpeg(cmd, "overlay-captions", timeout=MAX_RENDER_TIMEOUT_SEC)
            current_video = str(overlay_path)
        except RuntimeError as e:
            logger.warning(f"B-roll overlay failed (non-fatal, continuing without): {e}")

            # Fallback: at least burn captions if we have them
            if has_captions:
                captioned_path = work / "captioned.mp4"
                try:
                    _run_ffmpeg(
                        [
                            "ffmpeg", "-y",
                            "-i", current_video,
                            "-vf", f"ass={ass_path}",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                            "-threads", "2",
                            "-c:a", "copy",
                            str(captioned_path),
                        ],
                        "burn-captions-fallback",
                        timeout=MAX_RENDER_TIMEOUT_SEC,
                    )
                    current_video = str(captioned_path)
                except RuntimeError as e2:
                    logger.warning(f"Caption burn fallback failed (non-fatal): {e2}")

    elif has_captions:
        # Caption-only burn (no b-roll assets — unchanged behavior)
        captioned_path = work / "captioned.mp4"
        try:
            _run_ffmpeg(
                [
                    "ffmpeg", "-y",
                    "-i", current_video,
                    "-vf", f"ass={ass_path}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-threads", "2",
                    "-c:a", "copy",
                    str(captioned_path),
                ],
                "burn-captions",
                timeout=MAX_RENDER_TIMEOUT_SEC,
            )
            current_video = str(captioned_path)
        except RuntimeError as e:
            logger.warning(f"Caption burn failed (non-fatal, continuing without captions): {e}")

    # Step 5: Mix in music
    if edit_plan.music.enabled:
        music_path = _get_music_track(edit_plan.music.track_id)
        if music_path and Path(music_path).exists():
            music_out = work / "with_music.mp4"
            vol_db = edit_plan.music.target_volume_db

            # Get video duration for music loop/trim
            duration_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", current_video,
            ]
            dur_result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=10)
            video_duration = 60.0
            if dur_result.returncode == 0:
                try:
                    info = json.loads(dur_result.stdout)
                    video_duration = float(info["format"]["duration"])
                except Exception:
                    pass

            vol_linear = 10 ** (vol_db / 20.0)

            try:
                _run_ffmpeg(
                    [
                        "ffmpeg", "-y",
                        "-i", current_video,
                        "-stream_loop", "-1", "-i", music_path,
                        "-t", str(video_duration),
                        "-filter_complex",
                        f"[1:a]volume={vol_linear:.4f},atrim=0:{video_duration:.2f}[music];"
                        f"[0:a][music]amix=inputs=2:duration=shortest:dropout_transition=2[aout]",
                        "-map", "0:v", "-map", "[aout]",
                        "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "160k",
                        str(music_out),
                    ],
                    "mix-music",
                    timeout=MAX_RENDER_TIMEOUT_SEC,
                )
                current_video = str(music_out)
            except RuntimeError as e:
                logger.warning(f"Music mix failed (non-fatal, continuing without music): {e}")

    # Step 6: Final output REMUX (no re-encode; preserves quality + avoids extra load)
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", current_video,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ],
        "final-remux",
        timeout=MAX_RENDER_TIMEOUT_SEC,
    )

    logger.info(f"Render complete: {output_path}")
    return output_path

def _get_music_track(track_id: str) -> str | None:
    """Get path to a built-in music track."""
    # Try to find in the music directory
    for ext in [".mp3", ".wav", ".ogg", ".m4a"]:
        path = MUSIC_DIR / f"{track_id}{ext}"
        if path.exists() and path.stat().st_size > 100:
            return str(path)

    logger.warning(f"Music track not found: {track_id}")
    return None
