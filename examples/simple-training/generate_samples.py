"""Reproduce the three local fixture images. No API or model is involved."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SAMPLES = [
    ('01-shapes.png', '白色背景上，从左到右依次是一个红色正方形、一个蓝色圆形和一个绿色三角形。共有三个图形。正方形位于左侧，圆形位于中间，三角形位于右侧。'),
    ('02-count.png', '白色背景上，上方排列着两个蓝色圆形，下方排列着一个红色正方形。共有三个图形，其中圆形有两个，正方形有一个，没有三角形。'),
    ('03-position.png', '白色背景上，左上角是一个绿色三角形，右上角是一个红色正方形，下方中央是一个蓝色圆形。圆形位于另外两个图形的下方。'),
]


def generate():
    images = ROOT / 'images'
    images.mkdir(exist_ok=True)
    red, blue, green = '#e53935', '#1565c0', '#2e7d32'
    for index, (filename, _) in enumerate(SAMPLES):
        im = Image.new('RGB', (720, 440), 'white')
        draw = ImageDraw.Draw(im)
        if index == 0:
            draw.rectangle((60, 150, 200, 290), fill=red)
            draw.ellipse((280, 150, 420, 290), fill=blue)
            draw.polygon(((570, 135), (490, 290), (650, 290)), fill=green)
        elif index == 1:
            draw.ellipse((150, 50, 290, 190), fill=blue)
            draw.ellipse((430, 50, 570, 190), fill=blue)
            draw.rectangle((290, 260, 430, 400), fill=red)
        else:
            draw.polygon(((180, 40), (100, 190), (260, 190)), fill=green)
            draw.rectangle((460, 50, 600, 190), fill=red)
            draw.ellipse((290, 260, 430, 400), fill=blue)
        im.save(images / filename)
    rows = [{'id':f'sample-{i+1:02d}', 'text':text} for i, (_, text) in enumerate(SAMPLES)]
    (ROOT / 'text.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), 'utf-8')


if __name__ == '__main__':
    generate()
