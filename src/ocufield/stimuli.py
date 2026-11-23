from math import acos, atan2, ceil, cos, floor, hypot, pi, radians, sin, tan
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyglet import gl

from .logic import AXES, SLOTS, VEHICLE_HEIGHT, VEHICLE_WIDTH, stage_dimensions

SUPERSAMPLE = 4


def quadratic(start, control, end):
    return [
        tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t ** 2 * c for a, b, c in zip(start, control, end))
        for t in np.linspace(0, 1, 33)[1:]
    ]


def arc(x, y, radius, start, end):
    return [(x + radius * cos(a), y + radius * sin(a)) for a in np.linspace(start, end, 129)]


def rounded_polygon(points, radius):
    outline = []
    for index, (x, y) in enumerate(points):
        prev = points[index - 1]
        following = points[(index + 1) % len(points)]
        a = (prev[0] - x, prev[1] - y)
        b = (following[0] - x, following[1] - y)
        a = (a[0] / hypot(*a), a[1] / hypot(*a))
        b = (b[0] / hypot(*b), b[1] / hypot(*b))
        angle = acos(a[0] * b[0] + a[1] * b[1])
        length = radius / tan(angle / 2)
        cx, cy = x + (a[0] + b[0]) * length / (1 + cos(angle)), y + (a[1] + b[1]) * length / (1 + cos(angle))
        start = atan2(y + a[1] * length - cy, x + a[0] * length - cx)
        outline.extend(arc(cx, cy, radius, start, start + pi - angle))
    return outline


FRONT = [
    (51, 1.5), *quadratic((51, 1.5), (55.5, 1.5), (57.8, 6.5)), (71.5, 38.5),
    *quadratic((71.5, 38.5), (73.5, 43.5), (68, 44.5)),
    *arc(54.5, 44.5, 12, 0, -pi), (42.5, 46), (29.5, 46),
    *arc(17.5, 44.5, 12, 0, -pi),
]
CAR_ROOF_LINE = [(14.2, 6.5), *quadratic((14.2, 6.5), (16.5, 1.5), (21, 1.5))]
CAR_REAR = [*quadratic((5.5, 44.5), (-1.5, 43.5), (0.5, 38.5)), *CAR_ROOF_LINE]
TRUCK_REAR = [
    *quadratic((5.5, 44.5), (-1.5, 43.5), (0.5, 38.5)), (3.5, 31.5), (37.5, 31.5), (37.5, 3.5),
    *quadratic((37.5, 3.5), (37.5, 1.5), (39.5, 1.5)),
]
VEHICLE_BODY = {'car': [(21, 1.5), *FRONT, *CAR_REAR], 'truck': [(38.8, 1.5), *FRONT, *TRUCK_REAR]}
LEFT_WINDOW = rounded_polygon([(21, 5.5), (33.2, 5.5), (33.2, 21.5), (15, 21.5)], 3.5)
RIGHT_WINDOW = rounded_polygon([(38.8, 5.5), (51, 5.5), (57, 21.5), (38.8, 21.5)], 3.5)
WHEELS = [arc(x, 44.5, 8.5, 0, 2 * pi) for x in (17.5, 54.5)]
CHOICE_BODY = {
    'car': [(21, 1.5), *FRONT, (4.5, 44.5),
            *quadratic((4.5, 44.5), (-1.5, 43.5), (0.5, 38.5)), *CAR_ROOF_LINE],
    'truck': VEHICLE_BODY['truck'],
}
CHOICE_LEFT_WINDOW = [
    (24.5, 5.5), (30.2, 5.5), *quadratic((30.2, 5.5), (33.2, 5.5), (33.2, 8.5)),
    (33.2, 18.5), *quadratic((33.2, 18.5), (33.2, 21.5), (30.2, 21.5)),
    (17.5, 21.5), *quadratic((17.5, 21.5), (14.5, 21.5), (15.5, 18.5)),
    (20, 8.5), *quadratic((20, 8.5), (21, 5.5), (24.5, 5.5)),
]
CHOICE_RIGHT_WINDOW = [
    (41.8, 5.5), (47.5, 5.5), *quadratic((47.5, 5.5), (51, 5.5), (52, 8.5)),
    (56.5, 18.5), *quadratic((56.5, 18.5), (57.5, 21.5), (54.5, 21.5)),
    (41.8, 21.5), *quadratic((41.8, 21.5), (38.8, 21.5), (38.8, 18.5)),
    (38.8, 8.5), *quadratic((38.8, 8.5), (38.8, 5.5), (41.8, 5.5)),
]


def paint(image, shapes):
    points = [point for shape, _ in shapes for point in shape]
    left = max(0, floor(min(x for x, _ in points)))
    top = max(0, floor(min(y for _, y in points)))
    right = min(image.width, ceil(max(x for x, _ in points)))
    bottom = min(image.height, ceil(max(y for _, y in points)))
    if right <= left or bottom <= top:
        return
    size = (right - left, bottom - top)
    patch = Image.new('RGBA', tuple(d * SUPERSAMPLE for d in size))
    draw = ImageDraw.Draw(patch)
    for shape, color in shapes:
        points = [((x - left) * SUPERSAMPLE - 0.5, (y - top) * SUPERSAMPLE - 0.5) for x, y in shape]
        draw.polygon(points, color)
    patch = patch.resize(size, Image.Resampling.BOX)
    image.paste(patch, (left, top), patch.getchannel('A'))


def gray(level):
    return (level, level, level, 255)


def vehicle(image, x, y, target, scale, background, *, choice=False):
    body, left, right = ((CHOICE_BODY, CHOICE_LEFT_WINDOW, CHOICE_RIGHT_WINDOW)
                         if choice else (VEHICLE_BODY, LEFT_WINDOW, RIGHT_WINDOW))
    parts = [(body[target], gray(255)), (right, gray(background))]
    if target == 'car':
        parts.append((left, gray(background)))
    parts.extend((wheel, gray(255)) for wheel in WHEELS)
    paint(image, [
        ([(x + (a - VEHICLE_WIDTH / 2) * scale, y + (b - VEHICLE_HEIGHT / 2) * scale)
          for a, b in path], color)
        for path, color in parts
    ])


def square(x, y, size):
    h = size / 2
    return [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]


def center_box(image, x, y, size, border, background):
    paint(image, [(square(x, y, size), gray(255)), (square(x, y, size - border * 2), gray(background))])


def triangle(image, x, y, width, height, stroke, background):
    half = width / 2
    slope = hypot(half, height)

    def outline(offset):
        edge = half + offset * (slope + half) / height
        top = y - height / 2 - offset
        return [(x - edge, top), (x + edge, top), (x, y + height / 2 + offset * slope / half)]

    shapes = [(outline(stroke / 2), gray(255))]
    inside = outline(-stroke / 2)
    if inside[0][0] < inside[1][0] and inside[0][1] < inside[2][1]:
        shapes.append((inside, gray(background)))
    paint(image, shapes)


def trial_images(size, geometry, background, target, target_slot, distractors):
    fixation = Image.new('L', size, background)
    metric = stage_dimensions(*size, geometry)
    cx, cy = (d / 2 for d in size)
    center_box(fixation, cx, cy, metric['centerBoxSize'], metric['centerBoxBorder'], background)
    stimulus = fixation.copy()
    vehicle(stimulus, cx, cy, target, metric['vehicleScale'], background)
    if target_slot is not None:
        for slot in SLOTS:
            if slot != target_slot and not distractors:
                continue
            angle = radians(slot.angleDeg)
            radius = metric['radii'][slot.ring]
            x, y = cx + cos(angle) * radius, cy + sin(angle) * radius
            if slot == target_slot:
                vehicle(stimulus, x, y, 'car', metric['vehicleScale'], background)
            else:
                triangle(stimulus, x, y, metric['distractorWidth'], metric['distractorHeight'],
                         metric['distractorStroke'], background)
    return fixation, stimulus


def noise_image(size, rng):
    pixels = rng.integers(0, 2, size[::-1], dtype=np.uint8) * 255
    return Image.fromarray(pixels)


def response_images(size):
    width, height = size
    cx, cy = width / 2, height / 2
    base = min(size)
    font_file = Path(os.environ['WINDIR']) / 'Fonts' / 'msjhbd.ttc'
    central = Image.new('RGB', size)
    central_draw = ImageDraw.Draw(central)
    vehicle_hits = []
    button_width = (min(width, 520) - 16) / 2
    for index, target in enumerate(('car', 'truck')):
        x = cx + (index - 0.5) * (button_width + 16)
        box = (x - button_width / 2, cy - 38, x + button_width / 2, cy + 38)
        central_draw.rounded_rectangle(box, radius=10, outline='white', width=2)
        vehicle(central, x, cy, target, 54 / VEHICLE_WIDTH, 0, choice=True)
        vehicle_hits.append(box)

    axis_pad = Image.new('RGB', size)
    axis_draw = ImageDraw.Draw(axis_pad)
    axis_font = ImageFont.truetype(str(font_file), max(16, min(24, floor(base * 0.024))))
    radius = base * 0.4464
    centers = [
        (cx + cos(radians(-90 + axis * 45)) * radius, cy + sin(radians(-90 + axis * 45)) * radius)
        for axis in AXES
    ]
    for x, y in centers:
        axis_draw.line((cx, cy, x, y), fill='#454856')
    half = base * 0.1018 / 2
    axis_draw.rectangle((cx - half, cy - half, cx + half, cy + half),
                        fill='black', outline='white', width=max(2, round(base * 0.0028)))
    half = max(23, half)
    axis_hits = []
    for axis, (x, y) in enumerate(centers, 1):
        box = (x - half, y - half, x + half, y + half)
        axis_draw.rectangle(box, fill='white', outline='#d9d9d9')
        axis_draw.text((x, y), str(axis), font=axis_font, anchor='mm', fill='black')
        axis_hits.append(box)

    feedback_font = ImageFont.truetype(str(font_file), 36)
    feedback = {}
    feedback[True] = Image.new('RGB', size)
    ImageDraw.Draw(feedback[True]).line(
        [(cx - 10, cy), (cx - 3, cy + 8), (cx + 11, cy - 9)], fill='#4ade80', width=4, joint='curve',
    )
    feedback[False] = Image.new('RGB', size)
    ImageDraw.Draw(feedback[False]).text((cx, cy), '×', font=feedback_font, anchor='mm', fill='#ef4444')
    return (central, vehicle_hits), (axis_pad, axis_hits), feedback


class FrameTexture:
    def __init__(self, image):
        self.texture = gl.GLuint()
        gl.glGenTextures(1, self.texture)
        self.display_list = gl.glGenLists(1)
        if not self.texture.value or not self.display_list:
            self.close()
            raise RuntimeError('無法建立刺激畫面紋理')
        try:
            self.upload(image)
        except Exception:
            self.close()
            raise

    def upload(self, image):
        target = gl.GL_TEXTURE_2D
        gl.glBindTexture(target, self.texture)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexParameteri(target, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(target, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
        gl.glTexParameteri(target, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(target, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        pixel_format, internal = (gl.GL_LUMINANCE, gl.GL_LUMINANCE8) if image.mode == 'L' else (gl.GL_RGB, gl.GL_RGB8)
        gl.glTexImage2D(target, 0, internal, *image.size, 0, pixel_format, gl.GL_UNSIGNED_BYTE, image.tobytes())
        gl.glBindTexture(target, 0)

        gl.glNewList(self.display_list, gl.GL_COMPILE)
        gl.glPushAttrib(gl.GL_ENABLE_BIT | gl.GL_TEXTURE_BIT | gl.GL_CURRENT_BIT)
        for option in (gl.GL_BLEND, gl.GL_DEPTH_TEST, gl.GL_DITHER, gl.GL_SCISSOR_TEST):
            gl.glDisable(option)
        gl.glEnable(target)
        gl.glBindTexture(target, self.texture)
        gl.glTexEnvi(gl.GL_TEXTURE_ENV, gl.GL_TEXTURE_ENV_MODE, gl.GL_REPLACE)
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glBegin(gl.GL_QUADS)
        for u, v in ((0, 0), (0, 1), (1, 1), (1, 0)):
            gl.glTexCoord2i(u, v)
            gl.glVertex2i(2 * u - 1, 1 - 2 * v)
        gl.glEnd()
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_PROJECTION)
        gl.glPopMatrix()
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPopAttrib()
        gl.glEndList()
        self.draw()
        gl.glFinish()

    def draw(self):
        gl.glCallList(self.display_list)

    def close(self):
        if self.display_list:
            gl.glDeleteLists(self.display_list, 1)
        if self.texture.value:
            gl.glDeleteTextures(1, self.texture)
