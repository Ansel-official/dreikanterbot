"""生成 PWA 图标（可重复运行）。

用法：python scripts/generate_icons.py
依赖：Pillow
输出：frontend/public/icons/{icon-192,icon-512,icon-maskable-512,apple-touch-icon}.png
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

TOP = (109, 135, 255)
BOTTOM = (51, 76, 228)


def _vertical_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    for y in range(size):
        ratio = y / max(1, size - 1)
        color = (
            int(TOP[0] * (1 - ratio) + BOTTOM[0] * ratio),
            int(TOP[1] * (1 - ratio) + BOTTOM[1] * ratio),
            int(TOP[2] * (1 - ratio) + BOTTOM[2] * ratio),
            255,
        )
        for x in range(size):
            pixels[x, y] = color
    return image


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, outer: float, color: tuple) -> None:
    inner = outer * 0.24
    points = [
        (cx, cy - outer),
        (cx + inner, cy - inner),
        (cx + outer, cy),
        (cx + inner, cy + inner),
        (cx, cy + outer),
        (cx - inner, cy + inner),
        (cx - outer, cy),
        (cx - inner, cy - inner),
    ]
    draw.polygon(points, fill=color)


def render(*, rounded: bool) -> Image.Image:
    size = SIZE
    gradient = _vertical_gradient(size)

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([size * 0.55, -size * 0.18, size * 1.18, size * 0.42], fill=(255, 255, 255, 25))
    gd.ellipse([-size * 0.22, size * 0.58, size * 0.46, size * 1.22], fill=(8, 16, 60, 30))
    gradient = Image.alpha_composite(gradient, glow)

    draw = ImageDraw.Draw(gradient)

    # 对话气泡
    bubble = [size * 0.17, size * 0.205, size * 0.83, size * 0.705]
    draw.rounded_rectangle(bubble, radius=size * 0.145, fill=(255, 255, 255, 255))
    draw.polygon(
        [
            (size * 0.295, size * 0.665),
            (size * 0.435, size * 0.665),
            (size * 0.315, size * 0.845),
        ],
        fill=(255, 255, 255, 255),
    )

    # 气泡内的品牌星芒
    _star(draw, size * 0.5, size * 0.445, size * 0.185, (77, 107, 254, 255))
    _star(draw, size * 0.705, size * 0.325, size * 0.055, (122, 146, 255, 255))
    _star(draw, size * 0.31, size * 0.575, size * 0.04, (122, 146, 255, 255))

    if rounded:
        mask = _rounded_mask(size, int(size * 0.235))
        gradient.putalpha(mask)
    return gradient


def save(image: Image.Image, name: str, size: int) -> None:
    image.resize((size, size), Image.LANCZOS).save(OUT / name, format="PNG", optimize=True)
    print(f"wrote {OUT / name}")


def main() -> None:
    rounded = render(rounded=True)
    square = render(rounded=False)  # iOS / maskable 用满版背景
    save(rounded, "icon-512.png", 512)
    save(rounded, "icon-192.png", 192)
    save(square, "icon-maskable-512.png", 512)
    save(square, "apple-touch-icon.png", 180)


if __name__ == "__main__":
    main()
