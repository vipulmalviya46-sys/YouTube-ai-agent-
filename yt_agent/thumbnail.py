"""Thumbnail studio: several A/B variants from a video frame (or generated bg), with punchy outlined text,
vignette, saturation boost, and a self-check (1280x720, <2MB, <=4 words, text contrast)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .media import font_path

W, H = 1280, 720
STYLES = [  # (text colour, accent colour, text anchor)
    ("#FFFFFF", "#FFD400", "left"),
    ("#FFE600", "#FF2D55", "left"),
    ("#FFFFFF", "#00E5FF", "right"),
]


def _base(frame: Path | None, i: int) -> Image.Image:
    if frame and Path(frame).exists():
        img = Image.open(frame).convert("RGB")
        r = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * r), int(img.height * r)), Image.LANCZOS)
        l, t = (img.width - W) // 2, (img.height - H) // 2
        img = img.crop((l, t, l + W, t + H))
    else:
        img = Image.new("RGB", (W, H), (20, 20, 40))
        d = ImageDraw.Draw(img)
        for y in range(H):
            d.line([(0, y), (W, y)], fill=(20 + y // 12, 10 + (i * 30) % 60, 70 + y // 8))
    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    return img


def _vignette(img: Image.Image) -> Image.Image:
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((-W * 0.25, -H * 0.25, W * 1.25, H * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)), mask)


def _fit_font(text: str, max_w: int, max_h: int) -> ImageFont.FreeTypeFont:
    fp = font_path()
    size = 220
    while size > 40:
        f = ImageFont.truetype(fp, size) if fp else ImageFont.load_default()
        box = ImageDraw.Draw(Image.new("RGB", (10, 10))).multiline_textbbox((0, 0), text, font=f, stroke_width=10)
        if box[2] - box[0] <= max_w and box[3] - box[1] <= max_h:
            return f
        size -= 6
    return f


def make_variant(text: str, frame: Path | None, i: int, out: Path) -> Path:
    text = " ".join(text.upper().split()[:4])
    words = text.split()
    wrapped = "\n".join([" ".join(words[:2]), " ".join(words[2:])]) if len(words) > 2 else text
    col, accent, side = STYLES[i % len(STYLES)]
    img = _vignette(_base(frame, i))
    d = ImageDraw.Draw(img)
    font = _fit_font(wrapped, int(W * 0.62), int(H * 0.7))
    x = 60 if side == "left" else W - 60
    d.multiline_text((x, H / 2), wrapped, font=font, fill=col, anchor="lm" if side == "left" else "rm",
                     align=side, stroke_width=10, stroke_fill="black", spacing=10)
    d.rectangle((0, H - 18, W, H), fill=accent)  # accent bar = visual consistency across the channel
    q = 92
    while True:
        img.save(out, "JPEG", quality=q, optimize=True)
        if out.stat().st_size < 1_900_000 or q < 50:
            break
        q -= 8
    return out


def check(path: Path) -> dict:
    img = Image.open(path)
    vals = list(img.convert("L").resize((64, 36)).getdata())
    return {"size_ok": img.size == (W, H), "bytes_ok": path.stat().st_size < 2_000_000,
            "contrast": round((max(vals) - min(vals)) / 255, 2)}


def make_thumbnails(texts: list[str], frame: Path | None, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return [make_variant(t, frame, i, out_dir / f"thumb_{chr(65 + i)}.jpg") for i, t in enumerate(texts[:3])]
