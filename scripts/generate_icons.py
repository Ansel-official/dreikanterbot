"""生成 Dreikanterbot PWA 图标（可重复运行）。

设计：浅色背景 + 黑色圆角品牌块 + 白色 D + 一个蓝色小点，尽量接近 Apple 的克制风格。
用法：python scripts/generate_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)
FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\arialbd.ttf"),
    Path(r"C:\Windows\Fonts\segoeuib.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def render(*, rounded: bool, maskable: bool = False) -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (245, 245, 247, 255))
    draw = ImageDraw.Draw(image)

    mark_ratio = 0.56 if maskable else 0.68
    mark_size = int(SIZE * mark_ratio)
    left = (SIZE - mark_size) // 2
    top = (SIZE - mark_size) // 2 + (SIZE * 0.015 if maskable else 0)
    radius = int(mark_size * 0.235)
    draw.rounded_rectangle(
        [left, top, left + mark_size, top + mark_size],
        radius=radius,
        fill=(29, 29, 31, 255),
    )

    font = _font(int(mark_size * 0.64))
    text = "D"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = left + (mark_size - text_w) / 2 - bbox[0]
    text_y = top + (mark_size - text_h) / 2 - bbox[1] - mark_size * 0.025
    draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))

    dot = int(mark_size * 0.13)
    dot_x = left + mark_size - dot * 0.85
    dot_y = top + mark_size - dot * 0.85
    draw.ellipse(
        [dot_x - dot / 2, dot_y - dot / 2, dot_x + dot / 2, dot_y + dot / 2],
        fill=(0, 113, 227, 255),
    )

    if rounded:
        image.putalpha(_rounded_mask(SIZE, int(SIZE * 0.235)))
    return image


def save(image: Image.Image, name: str, size: int) -> None:
    image.resize((size, size), Image.LANCZOS).save(OUT / name, format="PNG", optimize=True)
    print(f"wrote {OUT / name}")


def main() -> None:
    rounded = render(rounded=True)
    square = render(rounded=False)
    maskable = render(rounded=False, maskable=True)
    save(rounded, "icon-512.png", 512)
    save(rounded, "icon-192.png", 192)
    save(maskable, "icon-maskable-512.png", 512)
    save(square, "apple-touch-icon.png", 180)


if __name__ == "__main__":
    main()
