from contextlib import ExitStack, contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime
import gc
from itertools import count
import os
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory

import numpy as np

from .export import DATE_TIME, json_data, number_text, write_csvs, write_json
from .logic import (
    FEEDBACK_MS, FIXATION_MS, INTER_TRIAL_MS, MASK_MS, MAX_TEST_TRIALS, PRACTICE_TRIALS,
    TARGET_SLOTS, Staircase, background_value, calculate_screen_geometry, estimate_threshold_ms,
    fastest_correct_stimulus_ms, fixed, formal_trial_decision, frames_to_ms, js_round,
    ms_to_frames, round_ms, update_staircase,
)
from .storage import monitor_refresh_hz, validate_config
from .timing import (
    MAX_TIMING_RETRIES, TIMING_ERROR, CadenceError, StimulusOverrun, stimulus_timing, wait_for_cadence,
)


class Aborted(Exception):
    pass


class GraphicsCheckError(RuntimeError):
    pass


@contextmanager
def runtime(scratch_dir=None):
    with TemporaryDirectory(prefix='ocufield-', dir=scratch_dir) as scratch:
        previous = os.environ['APPDATA']
        previous_mpl = os.environ.get('MPLCONFIGDIR')
        os.environ['APPDATA'] = scratch
        os.environ['MPLCONFIGDIR'] = scratch
        try:
            from psychopy import prefs
            prefs.connections['checkForUpdates'] = False
            prefs.connections['allowUsageStats'] = False
            prefs.hardware['highDPI'] = 0
            from psychopy import visual
        finally:
            os.environ['APPDATA'] = previous
        try:
            yield visual
        finally:
            if previous_mpl is None:
                os.environ.pop('MPLCONFIGDIR', None)
            else:
                os.environ['MPLCONFIGDIR'] = previous_mpl


class CursorSamples:
    def __init__(self, capacity, origin):
        self.origin = origin
        self.points = (wintypes.POINT * capacity)()
        point_pointer = ctypes.POINTER(wintypes.POINT)
        self.pointers = [
            ctypes.cast(ctypes.byref(self.points, index * ctypes.sizeof(wintypes.POINT)), point_pointer)
            for index in range(capacity)
        ]
        self.times = [0.0] * capacity
        self.read_cursor = ctypes.windll.user32.GetCursorPos

    def read(self, index, timestamp):
        self.read_cursor(self.pointers[index])
        self.times[index] = timestamp

    def trajectory(self, start):
        return [
            {'x': point.x - self.origin.x, 'y': point.y - self.origin.y, 't': js_round((timestamp - start) * 1000)}
            for point, timestamp in zip(self.points, self.times)
        ]


class Display:
    def __init__(self, window, fullscreen):
        from pyglet.window import key, mouse
        from psychopy import logging
        from .stimuli import FrameTexture, response_images

        self.clock = logging.defaultClock.getTime
        self.window = window
        self.handle = window.winHandle
        self.texture = FrameTexture
        self.size = tuple(map(int, window.frameBufferSize))
        self.cancelled = False
        self.responses = []
        self.responding = False
        self.left_button = mouse.LEFT
        self.escape = key.ESCAPE
        self.handle.set_caption('周邊視野訓練')
        self.handle.set_mouse_visible(False)
        self.handle.push_handlers(on_key_press=self.on_key, on_close=self.cancel,
                                  on_mouse_press=self.on_press, on_mouse_release=self.on_release)
        if fullscreen:
            self.handle.push_handlers(on_deactivate=self.cancel)
        self.user32 = ctypes.windll.user32
        self.user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        hwnd = window._hw_handle
        rect = wintypes.RECT()
        if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)) or self.size != (rect.right, rect.bottom):
            raise RuntimeError('視窗影格與螢幕實體像素不一致')
        with ExitStack() as resources:
            central, axis, feedback = response_images(self.size)
            self.central = (self.prepare(central[0], resources), central[1])
            self.axis = (self.prepare(axis[0], resources), axis[1])
            self.feedback = {correct: self.prepare(image, resources) for correct, image in feedback.items()}
            self.resources = resources.pop_all()

    def prepare(self, image, resources):
        texture = self.texture(image)
        resources.callback(texture.close)
        return texture.draw

    def cancel(self):
        self.cancelled = True
        return True

    def on_key(self, symbol, modifiers):
        if symbol == self.escape:
            return self.cancel()

    def on_press(self, x, y, button, modifiers):
        if self.responding and button == self.left_button:
            self.responses.append((True, x, self.size[1] - y, self.clock()))
            return True

    def on_release(self, x, y, button, modifiers):
        if self.responding and button == self.left_button:
            self.responses.append((False, x, self.size[1] - y, self.clock()))
            return True

    def flip(self):
        timestamp = self.window.flip()
        if self.cancelled:
            raise Aborted
        return timestamp

    def show_frame(self, draw):
        draw()
        return self.flip()

    def initial_refresh(self, nominal_ms):
        wait_for_cadence(self.flip, nominal_ms, 24 * nominal_ms)

    def fixation(self, draw, nominal_ms):
        return wait_for_cadence(lambda: self.show_frame(draw), nominal_ms, FIXATION_MS)

    def track_origin(self):
        origin = wintypes.POINT()
        if not self.user32.ClientToScreen(self.window._hw_handle, ctypes.byref(origin)):
            raise OSError('無法取得視窗的螢幕座標')
        return origin

    def response(self, screen, scripted, trajectory, origin, tracking_start):
        draw, boxes = screen
        read_cursor = self.user32.GetCursorPos
        point = wintypes.POINT()
        point_pointer = ctypes.byref(point)
        self.handle.set_mouse_visible(True)
        self.responding = True
        pressed = None
        try:
            onset = self.show_frame(draw)
            self.responses.clear()
            timestamp = onset
            while True:
                read_cursor(point_pointer)
                trajectory.append(dict(x=point.x - origin.x, y=point.y - origin.y,
                                       t=js_round((timestamp - tracking_start) * 1000)))
                if scripted is not None and timestamp > onset:
                    return scripted, onset, timestamp
                for down, x, y, when in self.responses:
                    hit = next((i for i, (left, top, right, bottom) in enumerate(boxes)
                                if left <= x < right and top <= y < bottom), None)
                    if down:
                        pressed = hit
                    else:
                        if hit is not None and hit == pressed:
                            return hit, onset, when
                        pressed = None
                self.responses.clear()
                timestamp = self.show_frame(draw)
        finally:
            self.responding = False
            self.responses.clear()

    def wait_until(self, draw, deadline):
        while self.clock() < deadline:
            self.show_frame(draw)

    def close(self):
        self.resources.close()


def trial(display, config, run, geometry, practice, number, rng, noise_rng, scripted, delay, nominal_hz):
    from .stimuli import noise_image, trial_images

    subtest = config['selectedSubtest']
    target = 'car' if rng.random() > 0.5 else 'truck'
    slot = None
    if subtest >= 2:
        choices = [item for item in TARGET_SLOTS if item.axis in config['selectedAxes']] or TARGET_SLOTS
        slot = rng.choice(choices)
    background = background_value(config['contrastPercent'])
    fixation, stimulus = trial_images(display.size, geometry, background, target, slot, subtest == 3)
    frames = run.practiceDurationFrames if practice else run.durationFrames
    origin = display.track_origin()
    stimulus_samples = CursorSamples(frames, origin)
    mask_frames = ms_to_frames(MASK_MS, run.refreshMs)
    mask_samples = CursorSamples(mask_frames, origin)
    stimulus_indices = iter(range(1, frames))
    show = display.show_frame
    with ExitStack() as resources:
        mask = display.prepare(noise_image(display.size, noise_rng), resources)
        stim = display.prepare(stimulus, resources)
        fix = display.prepare(fixation, resources)
        if delay:
            display.wait_until(*delay)
        tracking_start = display.fixation(fix, run.refreshMs)
        gc_enabled = gc.isenabled()
        gc.disable()
        actual_frames = 1
        try:
            onset = show(stim)
            stimulus_samples.read(0, onset)
            for index in stimulus_indices:
                stimulus_samples.read(index, show(stim))
                actual_frames = index + 1
            mask_onset = show(mask)
        finally:
            if gc_enabled:
                gc.enable()
        mask_samples.read(0, mask_onset)
        for index in range(1, mask_frames):
            mask_samples.read(index, show(mask))
        actual_ms, dropped = stimulus_timing(onset, mask_onset, frames, run.refreshMs)
        trajectory = []
        central_script = ('car', 'truck').index(target) if scripted else None
        chosen, response_start, response_end = display.response(display.central, central_script, trajectory, origin, tracking_start)
        central = ('car', 'truck')[chosen]
        peripheral = None
        if slot is not None:
            peripheral, _, response_end = display.response(
                display.axis, slot.axis if scripted else None, trajectory, origin, tracking_start
            )
        display.handle.set_mouse_visible(False)
    trajectory = stimulus_samples.trajectory(tracking_start) + mask_samples.trajectory(tracking_start) + trajectory
    central_correct = central == target
    peripheral_correct = peripheral == slot.axis if slot is not None else None
    record = dict(
        dateTime=datetime.now().strftime(DATE_TIME), subtestId=subtest, practice=practice,
        trialNumber=number, refreshHz=nominal_hz, refreshMs=run.refreshMs, durationFrames=frames,
        plannedDurationMs=frames_to_ms(frames, run.refreshMs), durationMs=actual_ms, actualDurationMs=actual_ms,
        actualFrameCount=actual_frames, droppedFrameCount=dropped,
        contrast=number_text(config['contrastPercent']) + '%', vehicleVisualAngle=fixed(config['vehicleVisualAngleDeg'], 1) + '°',
        centralTarget=target, centralResponse=central, centralCorrect=central_correct, peripheralCorrect=peripheral_correct,
        correct=central_correct and (slot is None or peripheral_correct),
        responseTimeMs=(response_end - response_start) * 1000, mouseTrajectory=trajectory,
    )
    if slot is not None:
        record.update(peripheralAxis=slot.axis, peripheralResponse=peripheral)
    return record, response_end


class HiddenSelfTestDisplay(Display):
    SIMULATED_HZ = 60

    def __init__(self, window, fullscreen):
        super().__init__(window, fullscreen)
        self.handle.set_vsync(False)
        self.flips = 0
        self.clock = lambda: self.flips / self.SIMULATED_HZ

    def flip(self):
        super().flip()
        self.flips += 1
        return self.clock()


def run_experiment(visual, config, *, fullscreen=True, scripted=False, size=(1920, 1080), monitor=None, hidden_test=False):
    if config['selectedMode'] == 'instruction':
        raise ValueError('說明模式沒有測驗題目')
    if hidden_test and (fullscreen or not scripted):
        raise ValueError('Simulated flip timestamps are only for windowed, scripted self-tests.')
    rng = Random(2806 if scripted else None)
    noise_rng = np.random.default_rng(509 if scripted else None)
    practice = config['selectedMode'] == 'practice'
    stop_rule = config['stopConditionType']
    limit = config['selectedTrialCount'] if stop_rule == 'fixed_trials' else MAX_TEST_TRIALS
    screen = 0
    if monitor is not None:
        import pyglet

        for index, item in enumerate(pyglet.canvas.get_display().get_screens()):
            if (item.x, item.y, item.width, item.height) == monitor:
                screen = index
                break
        else:
            raise RuntimeError('無法辨識已校準的螢幕')
        size = monitor[2:]
    with ExitStack() as resources:
        window = visual.Window(
            size=size, fullscr=fullscreen, screen=screen, winType='pyglet', units='pix',
            waitBlanking=True, gamma=None, color=(-1, -1, -1), useFBO=False,
            autoLog=False, checkTiming=False, allowGUI=not fullscreen,
        )
        resources.callback(window.close)
        display_type = HiddenSelfTestDisplay if hidden_test else Display
        display = display_type(window, fullscreen)
        resources.callback(display.close)
        verify_pixels(display)
        geometry = calculate_screen_geometry(
            config['screenWidthCm'], config['screenHeightCm'], config['viewingDistanceCm'],
            config['targetVisualAngleDeg'], config['vehicleVisualAngleDeg'], display.size,
        )
        nominal_hz = display.SIMULATED_HZ if hidden_test else monitor_refresh_hz(window._hw_handle)
        run = Staircase(round_ms(1000 / nominal_hz))
        trials = []
        aborted = False
        timing_stopped = False
        timing_invalid_repeats = 0
        delay = None
        numbers = range(1, PRACTICE_TRIALS + 1) if practice else count(1)
        try:
            display.initial_refresh(run.refreshMs)
            for number in numbers:
                for attempt in range(MAX_TIMING_RETRIES + 1):
                    try:
                        record, response_end = trial(
                            display, config, run, geometry, practice, number, rng, noise_rng, scripted, delay, nominal_hz,
                        )
                        break
                    except StimulusOverrun:
                        timing_invalid_repeats += 1
                        delay = None
                        if attempt == MAX_TIMING_RETRIES:
                            raise CadenceError(TIMING_ERROR)
                trials.append(record)
                if practice:
                    feedback = display.feedback[record['correct']]
                    delay = feedback, display.show_frame(feedback) + FEEDBACK_MS / 1000
                    continue
                update_staircase(run, record)
                done, aborted = formal_trial_decision(run, stop_rule, limit)
                if done:
                    break
                response_draw = display.axis[0] if config['selectedSubtest'] >= 2 else display.central[0]
                delay = response_draw, response_end + INTER_TRIAL_MS / 1000
                if aborted:
                    display.wait_until(*delay)
                    break
            if practice:
                display.wait_until(*delay)
        except CadenceError:
            aborted = timing_stopped = True
        if timing_stopped:
            fastest = fastest_correct_stimulus_ms(trials) or None
            threshold = None
        else:
            fallback = frames_to_ms(run.durationFrames, run.refreshMs)
            fastest = fastest_correct_stimulus_ms(trials, fallback)
            threshold = estimate_threshold_ms(run, trials, fastest) if not practice and not aborted else fastest
        return dict(
            trials=trials, geometry=geometry, refreshMs=run.refreshMs, refreshHz=nominal_hz,
            thresholdMs=threshold, fastestMs=fastest, aborted=aborted,
            timingStopped=timing_stopped, timingInvalidRepeats=timing_invalid_repeats,
        )


def verify_pixels(display):
    from PIL import Image

    info = dict.fromkeys(('GL_VENDOR', 'GL_RENDERER', 'GL_VERSION'))
    try:
        from pyglet import gl

        for _ in range(32):
            if gl.glGetError() == gl.GL_NO_ERROR:
                break
        else:
            raise RuntimeError('OpenGL errors did not clear before the pixel check')

        metadata_error = None
        for name in info:
            try:
                value = gl.glGetString(getattr(gl, name))
                if value:
                    info[name] = ctypes.string_at(value).decode('utf-8', errors='replace').strip()
            except Exception as error:
                metadata_error = error
        if not all(info.values()):
            raise RuntimeError('OpenGL identification unavailable') from metadata_error

        gl.glDrawBuffer(gl.GL_BACK)
        try:
            gl.glReadBuffer(gl.GL_BACK)
            w, h = display.size
            pattern = np.zeros((h, w), dtype=np.uint8)
            pattern[:h // 2, 1::2] = 255
            pattern[h // 2:, ::2] = 255
            with ExitStack() as resources:
                draw = display.prepare(Image.fromarray(pattern), resources)
                draw()
                pixels = (gl.GLubyte * (w * h * 3))()
                gl.glPushClientAttrib(gl.GL_CLIENT_PIXEL_STORE_BIT)
                try:
                    gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
                    gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, pixels)
                finally:
                    gl.glPopClientAttrib()
                actual = np.ctypeslib.as_array(pixels).reshape(h, w, 3)[::-1]
                if not np.all(actual == pattern[:, :, None]):
                    raise RuntimeError('OpenGL pixel readback did not match the test pattern')
        finally:
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        if gl.glGetError() != gl.GL_NO_ERROR:
            raise RuntimeError('OpenGL reported an error during the pixel check')
    except Exception as error:
        details = ' / '.join(f'{name}={value or "無法讀取"}' for name, value in info.items())
        raise GraphicsCheckError(
            'GRAPHICS_CHECK_FAILED 顯示卡驅動／繪圖環境無法正確呈現刺激，已停止施測，未產生資料。\n'
            + details
        ) from error


def self_test(visual, directory, *, verify_timing=True):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    reports = []
    timing = dict(timingVerified=verify_timing)
    if not verify_timing:
        timing['timingReason'] = 'The private desktop uses simulated flip timestamps and skips physical display cadence measurement.'
    for subtest in (1, 2, 3):
        config = validate_config(dict(selectedSubtest=subtest, selectedTrialCount=3, stopConditionType='fixed_trials'))
        config['subjectId'] = 'SUBJ_TEST01'
        result = run_experiment(visual, config, fullscreen=False, scripted=True, size=(481, 361),
                                hidden_test=not verify_timing)
        trials = result['trials']
        if result['aborted'] or len(trials) != 3 or not all(
            t['correct'] and t['durationFrames'] == t['actualFrameCount']
            and t['actualDurationMs'] > 0 and t['mouseTrajectory']
            and t['actualDurationMs'] >= t['plannedDurationMs'] * 0.75
            for t in trials
        ):
            raise RuntimeError(f'Subtest {subtest} 自我測試失敗')
        when = datetime.now()
        write_csvs(directory, config, result, when)
        write_json(directory / f'Subtest{subtest}.json', dict(json_data(config, result, when), **timing))
        reports.append(dict(subtestId=subtest, trials=[
            dict(plannedFrames=t['durationFrames'], actualFrames=t['actualFrameCount'],
                 plannedDurationMs=t['plannedDurationMs'], actualDurationMs=t['actualDurationMs'],
                 droppedFrames=t['droppedFrameCount'], refreshHz=t['refreshHz'], refreshMs=t['refreshMs'])
            for t in trials
        ], timingInvalidRepeats=result['timingInvalidRepeats']))
    write_json(directory / 'selftest.json', dict(success=True, subtests=reports, pixelAlignment=True, **timing))
