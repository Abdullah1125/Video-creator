"""Kids video pipeline: topic + language + design style -> finished MP4.

Claude writes the story (as a purffle-shorts compatible script.json) and draws every scene as a
hand-written SVG illustration in the chosen design style (no image-generation API, no extra cost
beyond the Claude calls themselves). The SVGs are rasterized to PNG and dropped into a per-job
media folder; purffle-shorts (https://github.com/Chamanrajragu/purffle-shorts) then picks them up
through its "local" visual source and handles narration (TTS), captions and the final ffmpeg render.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cairosvg
from anthropic import Anthropic

log = logging.getLogger("kidsvideo")

JOBS_ROOT = Path(os.environ.get("KIDS_JOBS_DIR", Path(__file__).resolve().parent.parent / "jobs"))

SCRIPT_MODEL = os.environ.get("KIDS_SCRIPT_MODEL", "claude-opus-5-5")
IMAGE_MODEL = os.environ.get("KIDS_IMAGE_MODEL", "claude-sonnet-5-5")

ASPECT_RESOLUTIONS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}

LANGUAGE_NAMES = {
    "tr": "Turkish", "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ar": "Arabic", "ru": "Russian", "ja": "Japanese",
    "ko": "Korean", "zh": "Chinese (Mandarin)", "nl": "Dutch", "pl": "Polish", "hi": "Hindi",
}

_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)


class PipelineError(RuntimeError):
    pass


@dataclass
class JobStatus:
    id: str
    stage: str = "queued"           # queued | script | illustrating | rendering | done | error
    detail: str = ""
    progress: float = 0.0            # 0..1
    video_path: Path | None = None
    error: str | None = None
    scenes_done: int = 0
    scenes_total: int = 0


_JOBS: dict[str, JobStatus] = {}


def get_job(job_id: str) -> JobStatus | None:
    return _JOBS.get(job_id)


def _client() -> Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise PipelineError("ANTHROPIC_API_KEY is not set. Put it in your .env file.")
    return Anthropic(api_key=key)


# --------------------------------------------------------------------------------------------------
# 1. Claude writes the children's story as a purffle-shorts compatible script
# --------------------------------------------------------------------------------------------------
SCRIPT_SYSTEM = (
    "You are a warm, gentle children's video scriptwriter and illustrator's art director. "
    "You write short read-aloud narration for young children and a precise art-direction note for "
    "every scene's illustration. You reply with a single JSON object and nothing else — no markdown, "
    "no commentary."
)


def _script_user_prompt(topic: str, language_code: str, design_style: str, age_range: str,
                         target_seconds: int) -> str:
    lang = LANGUAGE_NAMES.get(language_code, language_code)
    n_scenes = max(4, min(10, round(target_seconds / 6)))
    words = int(target_seconds * 2.0)  # a slower, clearer pace than adult shorts
    return f"""Write one short children's video.

Topic / subject (given by a parent): {topic}
Audience: children aged {age_range}
Language: {lang} — write narration, title, hook_text, description and hashtags in {lang}.
Design style for every illustration (give this to the artist, in English, however the topic is written): {design_style}

Rules:
- Gentle, warm, encouraging tone. Simple vocabulary a {age_range} year old can follow by ear.
- NOTHING scary, violent, sad-without-resolution, or inappropriate. No real people. If the topic names a
  historical or living person, tell the story only through established, age-appropriate, true facts.
- If the topic is a story idea, tell a complete tiny story: a clear beginning, a gentle problem, and a
  happy or reassuring resolution, with a one-line kind lesson at the end if it fits naturally.
- If the topic is a factual/educational subject (animals, science, how things work...), explain it simply
  with one vivid, concrete example a child can picture, like a kind teacher would.
- Total narration about {words} words, split into about {n_scenes} short scenes. Each scene is 1-3 short
  sentences, simple enough to read aloud slowly.
- Scene 1 opens warmly and makes the child want to keep watching — no "hello" or "in this video".
- The last scene ends softly and positively. No "follow for more", no calls to action — this is not social
  media content.
- search_query: 2-4 ENGLISH words naming the main subject(s) of that scene (e.g. "little fox", "sun rising"),
  used only to pick a matching illustration file. Always English, whatever the narration language.
- image_prompt: one ENGLISH sentence describing exactly what the illustration should show for that scene,
  vivid and concrete, written for an illustrator. Always English. Do not mention the design style here —
  it is added separately.
- emphasis: 0-2 words from that scene's narration (copied exactly as written there) that a child's ear
  should catch, or [] when nothing stands out.
- emoji: one emoji that fits the scene, or "" when none fits.
- title: a warm, simple title for the video, max 60 characters, in {lang}.
- hook_text: max 6 words shown on screen in the first seconds, in {lang}.
- description: 1-2 warm sentences in {lang}, no hashtags.
- hashtags: 3-5 relevant hashtags. tags: 6-12 simple keywords.
- category: one of education, entertainment, people, howto, pets, music, film.

Return JSON with keys: topic, title, hook_text, language, scenes (array of
{{narration, search_query, image_prompt, emphasis, emoji}}), description, hashtags, tags, category."""


def write_script(topic: str, language_code: str, design_style: str, age_range: str = "4-8",
                  target_seconds: int = 60) -> dict:
    client = _client()
    system = SCRIPT_SYSTEM
    user = _script_user_prompt(topic, language_code, design_style, age_range, target_seconds)
    resp = client.messages.create(
        model=SCRIPT_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    data = _extract_json(text)
    if not isinstance(data, dict) or not data.get("scenes"):
        raise PipelineError("Claude did not return a usable script.")
    data.setdefault("topic", topic)
    data.setdefault("language", language_code)
    data.setdefault("category", "education")
    data.setdefault("style", "story")
    data.setdefault("hashtags", [])
    data.setdefault("tags", [])
    return data


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise PipelineError("Claude's reply had no JSON object in it.")
    return json.loads(m.group(0))


# --------------------------------------------------------------------------------------------------
# 2. Claude draws each scene as a self-contained SVG illustration
# --------------------------------------------------------------------------------------------------
SVG_SYSTEM = (
    "You are a children's book vector illustrator. You draw scenes as clean, self-contained SVG "
    "markup. You reply with ONLY the <svg>...</svg> markup and nothing else — no markdown fences, "
    "no explanation."
)


def _svg_user_prompt(image_prompt: str, design_style: str, width: int, height: int) -> str:
    return f"""Draw this scene as a single SVG illustration for a children's video.

Scene: {image_prompt}
Design / art style: {design_style}

Requirements:
- A single <svg> element, viewBox="0 0 {width} {height}", filling the entire frame edge to edge with a
  background (no transparent or white gaps at the borders).
- Self-contained: only <svg>, <defs>, <linearGradient>/<radialGradient>, <path>, <circle>, <ellipse>,
  <rect>, <polygon>, <g> and similar vector primitives. No external images, fonts, scripts or <foreignObject>.
- No text, letters, numbers or words anywhere in the image.
- Bright, cheerful, child-friendly colors; simple, readable shapes; nothing frightening or violent.
- Fill of detail appropriate to the style given above.

Reply with only the SVG markup, starting with <svg and ending with </svg>."""


def draw_scene_svg(image_prompt: str, design_style: str, width: int, height: int) -> str:
    client = _client()
    resp = client.messages.create(
        model=IMAGE_MODEL,
        max_tokens=8000,
        system=SVG_SYSTEM,
        messages=[{"role": "user", "content": _svg_user_prompt(image_prompt, design_style, width, height)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    m = _SVG_RE.search(text)
    if not m:
        raise PipelineError("Claude did not return SVG markup for a scene illustration.")
    return m.group(0)


_FALLBACK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#ffd27a"/><stop offset="1" stop-color="#ff9ecb"/>'
    '</linearGradient></defs>'
    '<rect width="{w}" height="{h}" fill="url(#g)"/>'
    '<circle cx="{cx}" cy="{cy}" r="{r}" fill="#ffffff" opacity="0.35"/>'
    "</svg>"
)


def _scene_image(idx: int, image_prompt: str, design_style: str, width: int, height: int,
                  dest_dir: Path) -> Path:
    try:
        svg = draw_scene_svg(image_prompt, design_style, width, height)
    except Exception as e:  # keep the job going even if one scene's drawing fails
        log.warning("Scene %d illustration failed (%s); using a soft gradient instead.", idx, e)
        svg = _FALLBACK_SVG.format(w=width, h=height, cx=width * 0.5, cy=height * 0.4, r=width * 0.3)
    dest = dest_dir / f"scene{idx:02d}.png"
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(dest), output_width=width, output_height=height)
    return dest


def _scene_filename(idx: int, search_query: str) -> str:
    words = re.findall(r"[A-Za-z]+", search_query.lower())[:3]
    slug = "_".join(words) or "scene"
    return f"scene{idx:02d}_{slug}.png"


# --------------------------------------------------------------------------------------------------
# 3. Orchestration: build the job, render with purffle-shorts, report progress
# --------------------------------------------------------------------------------------------------
def run_job(job_id: str, topic: str, language_code: str, design_style: str, aspect: str = "16:9",
            age_range: str = "4-8", target_seconds: int = 60) -> None:
    status = JobStatus(id=job_id)
    _JOBS[job_id] = status
    job_dir = JOBS_ROOT / job_id
    media_dir = job_dir / "media"
    output_dir = job_dir / "output"
    media_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = ASPECT_RESOLUTIONS.get(aspect, ASPECT_RESOLUTIONS["16:9"])

    try:
        status.stage, status.detail = "script", "Hikaye yazılıyor..."
        data = write_script(topic, language_code, design_style, age_range, target_seconds)
        scenes = data["scenes"]
        status.scenes_total = len(scenes)

        status.stage = "illustrating"
        for idx, scene in enumerate(scenes):
            status.detail = f"Sahne çiziliyor {idx + 1}/{len(scenes)}..."
            image_prompt = scene.get("image_prompt") or scene.get("search_query") or topic
            png_path = _scene_image(idx, image_prompt, design_style, width, height, media_dir)
            search_query = scene.get("search_query") or topic
            final_path = media_dir / _scene_filename(idx, search_query)
            png_path.rename(final_path)
            status.scenes_done = idx + 1
            status.progress = 0.1 + 0.6 * (status.scenes_done / max(1, len(scenes)))

        script_path = job_dir / "script.json"
        script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        status.stage, status.detail, status.progress = "rendering", "Video oluşturuluyor (seslendirme ve altyazı)...", 0.75
        mp4_path = _render_with_purffle(script_path, media_dir, output_dir, language_code, aspect)

        status.video_path = mp4_path
        status.stage, status.detail, status.progress = "done", "Video hazır!", 1.0
    except Exception as e:
        log.exception("job %s failed", job_id)
        status.stage, status.error, status.detail = "error", str(e), f"Hata: {e}"


def _render_with_purffle(script_path: Path, media_dir: Path, output_dir: Path, language_code: str,
                          aspect: str) -> Path:
    env = dict(os.environ)
    env["MEDIA_DIR"] = str(media_dir)
    env["VISUAL_SOURCES"] = "local"
    env["OUTPUT_DIR"] = str(output_dir)
    env["LANGUAGE"] = language_code
    env["TTS_ENGINE"] = env.get("TTS_ENGINE", "edge")
    env["SCRIPT_REVIEW"] = "off"
    env["CAPTION_EMOJI"] = env.get("CAPTION_EMOJI", "true")
    env["MADE_FOR_KIDS"] = "true"

    cmd = [
        "python", "-m", "purffle_shorts", "make",
        "--script", str(script_path),
        "--no-upload",
        "--no-review",
        "--aspect", aspect,
        "--lang", language_code,
    ]
    result = subprocess.run(cmd, env=env, cwd=str(output_dir.parent), capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        raise PipelineError(
            f"purffle-shorts render failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    candidates = sorted(output_dir.rglob("short.mp4")) + sorted(output_dir.rglob("video.mp4"))
    if not candidates:
        candidates = sorted(output_dir.rglob("*.mp4"))
    if not candidates:
        raise PipelineError("Render finished but no MP4 file was found.")
    return candidates[-1]


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
