"""Style preset definitions."""

PRESETS = {
    "snappy-creator": {
        "id": "snappy-creator",
        "name": "Snappy Creator",
        "description": "Fast cuts, frequent punch-ins, energetic captions",
        "config": {
            "target_duration_sec": 45,
            "silence_trim_ms": 300,
            "max_cuts": 30,
            "max_broll_clips": 4,
            "punch_in_scale_range": [1.08, 1.18],
            "caption_style": {
                "style_id": "helvetica_punch",
                "font_size": 64,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "outline_width": 3,
                "shadow_depth": 1,
                "position": "bottom-center",
                "animation": "pop",
                "max_words_per_line": 3,
                "max_lines": 1,
            },
            "music_pack_tags": ["energetic", "upbeat", "fast"],
            "default_music_track": "upbeat-energy",
        },
    },
    "cinematic-doc": {
        "id": "cinematic-doc",
        "name": "Cinematic Doc",
        "description": "Slower pacing, subtle zooms, fewer cuts",
        "config": {
            "target_duration_sec": 60,
            "silence_trim_ms": 500,
            "max_cuts": 15,
            "max_broll_clips": 3,
            "punch_in_scale_range": [1.04, 1.10],
            "caption_style": {
                "style_id": "cinematic",
                "font_size": 48,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "outline_width": 2,
                "shadow_depth": 3,
                "position": "bottom-center",
                "animation": "fade",
                "max_words_per_line": 6,
                "max_lines": 2,
            },
            "music_pack_tags": ["cinematic", "ambient", "calm"],
            "default_music_track": "cinematic-ambient",
        },
    },
    "podcast-clipper": {
        "id": "podcast-clipper",
        "name": "Podcast Clipper",
        "description": "Clean captions, fewer b-roll, strong silence removal",
        "config": {
            "target_duration_sec": 50,
            "silence_trim_ms": 250,
            "max_cuts": 25,
            "max_broll_clips": 2,
            "punch_in_scale_range": [1.06, 1.12],
            "caption_style": {
                "style_id": "podcast",
                "font_size": 52,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "outline_width": 2,
                "shadow_depth": 1,
                "position": "bottom-center",
                "animation": "none",
                "max_words_per_line": 5,
                "max_lines": 2,
            },
            "music_pack_tags": ["clean", "minimal", "neutral"],
            "default_music_track": "clean-podcast",
        },
    },
    "luxury-real-estate": {
        "id": "luxury-real-estate",
        "name": "Luxury Real Estate",
        "description": "Smooth pacing, elegant captions, calmer music",
        "config": {
            "target_duration_sec": 55,
            "silence_trim_ms": 400,
            "max_cuts": 12,
            "max_broll_clips": 4,
            "punch_in_scale_range": [1.04, 1.08],
            "caption_style": {
                "style_id": "luxury",
                "font_size": 44,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "outline_width": 1,
                "shadow_depth": 2,
                "position": "bottom-center",
                "animation": "fade",
                "max_words_per_line": 6,
                "max_lines": 2,
            },
            "music_pack_tags": ["luxury", "smooth", "elegant"],
            "default_music_track": "luxury-smooth",
        },
    },
    "study-explainer": {
        "id": "study-explainer",
        "name": "Study / Explainer",
        "description": "Structured, minimal effects, high readability captions",
        "config": {
            "target_duration_sec": 60,
            "silence_trim_ms": 350,
            "max_cuts": 20,
            "max_broll_clips": 3,
            "punch_in_scale_range": [1.04, 1.10],
            "caption_style": {
                "style_id": "study",
                "font_size": 50,
                "font_color": "&H00FFFFFF",
                "outline_color": "&H00000000",
                "outline_width": 2,
                "shadow_depth": 1,
                "position": "bottom-center",
                "animation": "none",
                "max_words_per_line": 6,
                "max_lines": 2,
            },
            "music_pack_tags": ["study", "focus", "lofi", "calm"],
            "default_music_track": "study-lofi",
        },
    },
}


def get_preset(preset_id: str) -> dict | None:
    return PRESETS.get(preset_id)


def list_presets() -> list[dict]:
    return [
        {"id": p["id"], "name": p["name"], "description": p["description"], "config": p["config"]}
        for p in PRESETS.values()
    ]
