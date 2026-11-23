from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback

from .experiment import Aborted, run_experiment
from .timing import TIMING_ERROR
from .export import DATE_TIME, json_data, number_text, write_csvs, write_json
from .logic import (
    ARROWS, AXES, COMPASS, DIRECTIONS, INSTRUCTIONS, SUBTEST_TITLES, VEHICLES, background_value,
    calculate_screen_geometry, direction_stats, fixed, js_round, percent, rendered_eccentricity,
)
from .storage import DEFAULTS, RANGES, downloads_path, load_config, monitor_rect, new_subject_id, save_config, validate_config

FONT = 'Microsoft JhengHei'
BG, PANEL, CARD, LINE, TEXT, MUTED = '#09090b', '#141417', '#1c1d22', '#454856', '#f4f4f5', '#a1a1aa'
GREEN, AMBER, RED = '#4ade80', '#fbbf24', '#f87171'
TABLE_HEADERS = ('題次', '刺激呈現時間', '更新率 (FPS)', '中央車型', '周邊方位', '中央回答', '周邊回答', '作答反應', '判定')


class App:
    def __init__(self, root, visual):
        self.root = root
        self.visual = visual
        self.root.title('周邊視野訓練')
        self.root.configure(background=BG)
        self.root.tk.call('tk', 'scaling', 4 / 3)
        self.root.option_add('*Font', (FONT, 11))
        self.root.update_idletasks()
        _, _, width, height = monitor_rect(self.root.winfo_id())
        self.root.geometry(f'{min(1020, int(width * 0.88))}x{min(860, int(height * 0.83))}')
        self.root.minsize(min(720, int(width * 0.85)), min(510, int(height * 0.8)))
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.report_callback_exception = self.callback_error
        self.root.bind('<Escape>', self.escape)
        self.root.bind('<MouseWheel>', self.wheel)
        self.root.bind('<Configure>', self.resize, add='+')
        self.root.bind('<FocusIn>', self.reveal_focus, add='+')
        self.root.bind_class('TButton', '<Return>', lambda event: event.widget.invoke())
        self.style()
        self.subject = new_subject_id()
        self.pending_save = None
        self.persisted = None
        self.result = None
        self.saved = False
        self.load_error = ''
        try:
            self.config = load_config()
        except (OSError, ValueError) as error:
            self.config = validate_config({})
            self.load_error = f'無法讀取設定，已載入預設值。{error}'
        else:
            self.persisted = self.config.copy()
        self.settings()

    def style(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=(FONT, 11), foreground=TEXT, background=PANEL, bordercolor=LINE,
                        lightcolor=PANEL, darkcolor=PANEL, focuscolor='white', troughcolor=BG,
                        arrowcolor=TEXT, fieldbackground=BG, insertcolor=TEXT)
        style.configure('TButton', background=CARD, padding=(12, 7))
        style.configure('Primary.TButton', background='#ffffff', foreground='#09090b', focuscolor='#2563eb')
        style.map('TButton', background=[('pressed', LINE), ('active', '#30313a')])
        style.map('Primary.TButton', background=[('pressed', '#d4d4d8'), ('active', '#e4e4e7')])
        style.configure('TRadiobutton', padding=(4, 4), indicatorbackground=BG, indicatorforeground=TEXT)
        style.map('TRadiobutton', indicatorbackground=[('selected', '#ffffff')], indicatorforeground=[('selected', BG)])
        style.configure('Direction.TCheckbutton', padding=(9, 8), background=CARD, indicatorbackground=BG)
        style.map('Direction.TCheckbutton', background=[('selected', '#35363f'), ('active', LINE)],
                  indicatorbackground=[('selected', '#ffffff')], indicatorforeground=[('selected', BG)])
        style.configure('Treeview', background=CARD, fieldbackground=CARD, rowheight=30)
        style.configure('Treeview.Heading', font=(FONT, 10, 'bold'), foreground=TEXT)

    def callback_error(self, error_type, error, trace):
        traceback.print_exception(error_type, error, trace)
        messagebox.showerror('周邊視野訓練', str(error), parent=self.root)

    def label(self, parent, caption='', size=11, *, bold=False, color=TEXT, bg=PANEL, **kwargs):
        label = tk.Label(parent, text=caption, font=(FONT, size, 'bold' if bold else 'normal'),
                         bg=bg, fg=color, anchor='w', justify='left', **kwargs)
        label.pack(fill='x')
        return label

    def page(self, name, title, detail=''):
        if hasattr(self, 'shell'):
            self.shell.destroy()
        self.page_name = name
        self.shell = tk.Frame(self.root, bg=PANEL)
        self.shell.pack(fill='both', expand=True, padx=14, pady=12)
        heading = tk.Frame(self.shell, bg=PANEL, padx=22, pady=15)
        heading.pack(fill='x')
        self.label(heading, '視覺注意力復能系統', 10, color=MUTED)
        self.label(heading, title, 19, bold=True)
        if detail:
            self.label(heading, detail, 10, color=MUTED, wraplength=600)
        ttk.Separator(self.shell).pack(fill='x')
        self.footer = tk.Frame(self.shell, bg=PANEL, padx=22, pady=10)
        self.footer.pack(side='bottom', fill='x')
        ttk.Separator(self.shell).pack(side='bottom', fill='x')
        self.canvas = tk.Canvas(self.shell, bg=PANEL, highlightthickness=0, yscrollincrement=20)
        bar = ttk.Scrollbar(self.shell, orient='vertical', command=self.canvas.yview)
        bar.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.configure(yscrollcommand=bar.set)
        self.body = tk.Frame(self.canvas, bg=PANEL, padx=22, pady=10)
        item = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(item, width=e.width))
        self.canvas.yview_moveto(0)
        self.status = self.label(self.footer, self.load_error, 10, color=AMBER, wraplength=610)

    def buttons(self, *actions):
        for index, (label, command) in enumerate(actions):
            ttk.Button(self.footer, text=label, command=command,
                       cursor='hand2', style='Primary.TButton' if index == 0 else 'TButton').pack(side='right', padx=(8, 0))

    def section(self, title, description=''):
        group = tk.Frame(self.body, bg=PANEL, pady=8)
        group.pack(fill='x')
        self.label(group, title, 12, bold=True)
        if description:
            self.label(group, description, 10, color=MUTED, wraplength=615)
        part = tk.Frame(group, bg=PANEL, pady=5)
        part.pack(fill='x')
        ttk.Separator(self.body).pack(fill='x', pady=2)
        return part

    def wheel(self, event):
        if isinstance(event.widget, ttk.Treeview):
            return
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def reveal_focus(self, event):
        if not hasattr(self, 'body') or not str(event.widget).startswith(str(self.body) + '.'):
            return
        top = event.widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        region = self.body.winfo_height()
        a, b = self.canvas.yview()
        if top < a * region:
            self.canvas.yview_moveto(max(0, top - 20) / region)
        elif bottom > b * region:
            self.canvas.yview_moveto((bottom - self.canvas.winfo_height() + 20) / region)

    def resize(self, event):
        if event.widget == self.root and getattr(self, 'page_name', '') == 'settings' and hasattr(self, 'geo'):
            self.update_geometry()

    def escape(self, _):
        if self.page_name in ('rules', 'instruction'):
            self.settings()

    def settings(self):
        self.page('settings', '周邊視野訓練設定')
        subject = self.section('受試者 ID / 編號 (Subject ID)', '輸入受試者代號，將自動同步記錄於每次測驗生成的 CSV 報告與統計成績中')
        self.subject_var = tk.StringVar(value=self.subject)
        field = ttk.Entry(subject, textvariable=self.subject_var)
        field.pack(side='left', fill='x', expand=True, ipady=5)
        ttk.Button(subject, text='隨機產生', cursor='hand2',
                   command=lambda: self.subject_var.set(new_subject_id())).pack(side='right', padx=(8, 0))
        self.vars = {}
        subtest = self.section('1. 選擇 Subtest 核心訓練項目', '支援處理速度、分散注意力與選擇性注意力評估')
        self.choices(subtest, 'selectedSubtest', tuple(enumerate(SUBTEST_TITLES, 1)), tk.IntVar)
        calibration = self.section('2. 螢幕尺寸與觀看距離校準', '輸入螢幕實際尺寸與距離，系統自動計算最大可測視角與像素比例')
        fields = tk.Frame(calibration, bg=PANEL)
        fields.pack(fill='x')
        for index, (key, caption) in enumerate(zip(
            ('screenWidthCm', 'screenHeightCm', 'viewingDistanceCm'),
            ('螢幕顯示寬度 (cm)', '螢幕顯示高度 (cm)', '觀看距離 (cm)'),
        )):
            cell = tk.Frame(fields, bg=PANEL)
            cell.grid(row=0, column=index, sticky='ew', padx=(0, 10))
            fields.columnconfigure(index, weight=1)
            self.label(cell, caption, 10, color=MUTED)
            var = self.vars[key] = tk.StringVar(value=number_text(self.config[key]))
            ttk.Entry(cell, textvariable=var, width=12).pack(fill='x', ipady=4)
        self.geo = self.label(calibration, '', 10, color=MUTED)
        self.warning = self.label(calibration, '', 10, color=AMBER, wraplength=620)
        adjust = self.section('3. 周邊偏心視角與車子大小')
        self.slider(adjust, 'targetVisualAngleDeg', '周邊偏心視角 (Eccentricity)', 0.5, '°')
        self.slider(adjust, 'vehicleVisualAngleDeg', '車子大小視角 (Vehicle Size)', 0.1, '°')
        contrast = self.section('4. 對比度控制 (Contrast)', '調整底色控制對比，目標物始終為白色')
        self.swatch = tk.Frame(contrast, width=30, height=18, highlightthickness=1, highlightbackground=MUTED)
        self.swatch.pack(side='right', padx=(14, 4))
        self.slider(contrast, 'contrastPercent', '對比度強度', 1, '%')
        directions = self.section('5. 刺激呈現方向 (九宮格方位選擇)',
                                  '按照空間九宮格方位排列，點擊各方位開關或點擊中央快速全選')
        self.axes = list(self.config['selectedAxes'])
        self.axis_vars = {axis: tk.BooleanVar() for axis in COMPASS}
        self.axis_total = self.label(directions, '', 10, color=MUTED)
        grid = tk.Frame(directions, bg=PANEL)
        grid.pack(anchor='w', pady=4)
        for index, axis in enumerate(COMPASS):
            button = ttk.Checkbutton(grid, text=f'{ARROWS[axis]}  {DIRECTIONS[axis]}' if axis is not None else 'ALL  全選',
                                     variable=self.axis_vars[axis], command=lambda axis=axis: self.toggle_axis(axis),
                                     style='Direction.TCheckbutton', cursor='hand2')
            button.grid(row=index // 3, column=index % 3, sticky='ew', padx=3, pady=3)
            grid.columnconfigure(index % 3, weight=1, minsize=116)
            if axis is None:
                self.all_button = button
        self.sync_axes()
        protocol = self.section('6. 測驗流程與停止條件')
        self.label(protocol, '測驗流程', 10, color=MUTED)
        self.choices(protocol, 'selectedMode', (('formal', '正式紀錄'), ('practice', '練習模式'), ('instruction', '說明')), tk.StringVar)
        self.label(protocol, '終止條件', 10, color=MUTED)
        count_label = number_text(self.config['selectedTrialCount'])
        self.choices(protocol, 'stopConditionType', (
            ('adaptive_80', '信度 80% 門檻 (推薦)'), ('fixed_trials', f'固定題數 ({count_label}題)'),
        ), tk.StringVar)
        for var in self.vars.values():
            var.trace_add('write', self.setting_changed)
        self.buttons(('進入規則說明與開始', self.rules))
        self.update_geometry()
        field.focus_set()

    def choices(self, parent, key, choices, vartype):
        var = self.vars[key] = vartype(value=self.config[key])
        for value, caption in choices:
            ttk.Radiobutton(parent, text=caption, value=value, variable=var, takefocus=True, cursor='hand2').pack(anchor='w')

    def slider(self, parent, key, title, step, suffix):
        var = self.vars[key] = tk.DoubleVar(value=self.config[key])
        wrapper = tk.Frame(parent, bg=PANEL)
        wrapper.pack(fill='x', expand=True)
        value = tk.StringVar()

        def update(*_):
            text = fixed(var.get(), 1) if suffix == '°' else number_text(var.get())
            value.set(f'{title}    {text}{suffix}')

        var.trace_add('write', update)
        update()
        self.label(wrapper, textvariable=value, size=10, color=MUTED)
        minimum, maximum = RANGES[key]
        scale = tk.Scale(wrapper, showvalue=False, orient='horizontal', variable=var, from_=minimum, to=maximum,
                         resolution=step, bg=PANEL, fg=TEXT, activebackground=TEXT, troughcolor=LINE,
                         highlightthickness=1, highlightbackground=PANEL, highlightcolor='white', bd=1,
                         takefocus=True)
        scale.pack(fill='x', pady=(0, 4))

    def toggle_axis(self, axis):
        if axis is None:
            self.axes = [0, 2, 4, 6] if len(self.axes) == 8 else list(AXES)
        elif axis not in self.axes:
            self.axes = sorted([*self.axes, axis])
        elif len(self.axes) > 1:
            remaining = [item for item in self.axes if item != axis]
            if remaining:
                self.axes = remaining
        self.sync_axes()
        self.setting_changed()

    def sync_axes(self):
        for axis in AXES:
            self.axis_vars[axis].set(axis in self.axes)
        is_all = len(self.axes) == 8
        self.axis_vars[None].set(is_all)
        self.all_button.configure(text='ALL  全選中' if is_all else 'ALL  全選')
        self.axis_total.configure(text=f'{len(self.axes)}/8 方向啟用')

    def read_settings(self):
        data = dict(self.config, selectedAxes=list(self.axes))
        for key, var in self.vars.items():
            value = var.get()
            if key in RANGES:
                try:
                    value = float(value)
                except ValueError as error:
                    raise ValueError('請輸入有效的螢幕尺寸與觀看距離。') from error
                low, high = RANGES[key]
                if not low <= value <= high:
                    raise ValueError(f'請輸入介於 {low} 和 {high} 之間的設定值。')
            data[key] = value
        return validate_config(data)

    def preview_geometry(self, config):
        return calculate_screen_geometry(
            config['screenWidthCm'], config['screenHeightCm'], config['viewingDistanceCm'],
            config['targetVisualAngleDeg'], config['vehicleVisualAngleDeg'], monitor_rect(self.root.winfo_id())[2:],
        )

    def update_geometry(self):
        try:
            config = self.read_settings()
        except (ValueError, tk.TclError):
            self.geo.configure(text='請輸入有效的螢幕尺寸與觀看距離。')
            self.warning.configure(text='')
            return
        geometry = self.preview_geometry(config)
        set_angle = config['targetVisualAngleDeg']
        eccentricity = rendered_eccentricity(geometry, set_angle, config['viewingDistanceCm'])
        angle = fixed(eccentricity.render_limit_deg, 2)
        self.geo.configure(text=f"計算像素密度: {js_round(geometry['ppcm'])} PPCM  |  畫面呈現視角上限: {angle}°"
                                f"  |  車輛渲染寬度: {js_round(geometry['vehicleWidthPx'])} px")
        warning = ''
        if eccentricity.clamped:
            warning = (f'設定偏心視角為 {fixed(set_angle, 1)}°，受畫面呈現範圍限制，'
                       f'實際偏心視角為 {fixed(eccentricity.actual_deg, 2)}°。\n'
                       f'建議將觀看距離縮短至 {fixed(eccentricity.fit_distance_cm, 2)} cm 以下，或降低偏心視角設定。')
        elif geometry['isOverLimit']:
            physical_limit = fixed(geometry['maxVisualAngleDeg'], 2)
            warning = (f'設定偏心視角為 {fixed(set_angle, 1)}°，超過依實體螢幕尺寸估算的上限 {physical_limit}°。'
                       '請確認螢幕尺寸與觀看距離。')
        self.warning.configure(text=warning)
        value = background_value(config['contrastPercent'])
        self.swatch.configure(bg=f'#{value:02x}{value:02x}{value:02x}')

    def setting_changed(self, *_):
        self.update_geometry()
        if self.pending_save is not None:
            self.root.after_cancel(self.pending_save)
        self.pending_save = self.root.after(350, self.persist)

    def persist(self, *, notify=False):
        if self.pending_save is not None:
            self.root.after_cancel(self.pending_save)
            self.pending_save = None
        try:
            config = self.read_settings()
        except ValueError as error:
            if notify:
                messagebox.showerror('設定錯誤', str(error), parent=self.root)
            return False
        self.config = config
        try:
            if self.config != self.persisted:
                save_config(config)
                self.persisted = self.config.copy()
                self.load_error = ''
        except OSError as error:
            self.load_error = f'無法儲存設定。{error}'
        self.status.configure(text=self.load_error)
        return True

    def rules(self):
        if not self.persist(notify=True):
            return
        config = self.config
        subtest = config['selectedSubtest'] - 1
        self.subject = self.subject_var.get().strip() or new_subject_id()
        set_angle = config['targetVisualAngleDeg']
        eccentricity = rendered_eccentricity(self.preview_geometry(config), set_angle, config['viewingDistanceCm'])
        angle = f'{fixed(set_angle, 1)}°'
        if eccentricity.clamped:
            angle += f'（實際 {fixed(eccentricity.actual_deg, 2)}°）'
        detail = (f"對比度: {number_text(config['contrastPercent'])}%  |  "
                  f"設定偏心視角: {angle}  |  "
                  f"車輛大小: {fixed(config['vehicleVisualAngleDeg'], 1)}°")
        self.page('rules', SUBTEST_TITLES[subtest], detail)
        section = self.section('任務目標與操作說明', INSTRUCTIONS[subtest])
        for rule in (
            '中央刺激辨識：每題刺激閃爍呈現後，點擊回答中央車輛是「汽車」或「卡車」。',
            '周邊方位回報：' + ('中央選擇完成後，指出周邊目標車輛所在的方向方位。'
                                if subtest else '此 Subtest 僅需辨識中央目標。'),
            '手眼協調與猶豫度：測驗全程記錄反應時間與滑鼠移動軌跡，作為臨床復能評估指標。',
            '自適應速度測試：正式模式會根據作答即時調節呈現時間，測量信度達 80% 之極限處理速度。',
        ):
            self.label(section, rule, wraplength=615).pack_configure(pady=8)
        self.buttons(('開始測驗訓練', self.start), ('返回修改設定', self.settings))

    def start(self):
        if self.config['selectedMode'] == 'instruction':
            subtest = self.config['selectedSubtest'] - 1
            self.page('instruction', SUBTEST_TITLES[subtest], INSTRUCTIONS[subtest])
            self.buttons(('返回設定', self.settings))
            return
        monitor = monitor_rect(self.root.winfo_id())
        self.run_config = dict(self.config, subjectId=self.subject)
        self.result = None
        self.root.withdraw()
        self.root.update_idletasks()
        try:
            self.result = run_experiment(self.visual, self.run_config, monitor=monitor)
        except Aborted:
            pass
        except Exception as error:
            self.root.deiconify()
            messagebox.showerror('測驗無法完成', str(error), parent=self.root)
        finally:
            self.root.deiconify()
        if self.result is None:
            self.settings()
            return
        self.finished = datetime.now()
        self.saved = False
        self.results()
        if self.result['trials']:
            self.save_csv()

    def results(self):
        result = self.result
        config = self.run_config
        self.page('results', '測驗結果與空間分析', f'測試時間：{self.finished:{DATE_TIME}}')
        trials = result['trials']
        formal = [t for t in trials if not t['practice']]
        correct = sum(t['correct'] for t in formal)
        threshold = result['thresholdMs']
        fastest = result['fastestMs']
        summaries = (
            ('處理速度反應門檻 (final_rt)', f'{number_text(threshold)} ms' if threshold is not None else '--'),
            ('最快正確呈現時間', f'{number_text(fastest)} ms' if fastest is not None else '--'),
            ('整體正確率', f'{percent(correct, len(formal))}%   {correct} / {len(formal)} 題'),
            ('螢幕標稱更新率', f"{result['refreshHz']} Hz ({number_text(result['refreshMs'])} ms)"),
            ('對比度', f"{number_text(config['contrastPercent'])}%"),
        )
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill='x', pady=(0, 10))
        for index, (title, value) in enumerate(summaries):
            color = '#212b40' if index == 0 else CARD
            card = tk.Frame(row, bg=color, padx=8, pady=8)
            card.grid(row=0, column=index, sticky='nsew', padx=(0, 4))
            row.columnconfigure(index, weight=1, uniform='summary')
            self.label(card, title, 9, color=MUTED, bg=color, wraplength=110)
            self.label(card, value, 11, bold=True, bg=color, wraplength=110)
        set_angle = config['targetVisualAngleDeg']
        eccentricity = rendered_eccentricity(result['geometry'], set_angle, config['viewingDistanceCm'])
        angle_note = f'設定偏心視角 {fixed(set_angle, 1)}°　實際偏心視角 {fixed(eccentricity.actual_deg, 2)}°'
        if eccentricity.clamped:
            angle_note += '（受畫面呈現範圍限制）'
        self.label(self.body, angle_note, 10, color=AMBER if eccentricity.clamped else MUTED, wraplength=610)
        if result['timingStopped']:
            detail = '已保留完成的題次。' if trials else '本次沒有完成題次。'
            self.label(self.body, TIMING_ERROR + detail, 11, bold=True, color=AMBER, wraplength=610)
        elif result['aborted']:
            self.label(self.body, '已中止', 11, bold=True, color=AMBER)
        self.label(self.body, f"因時序異常作廢的呈現次數：{result['timingInvalidRepeats']}", 10, color=MUTED)
        directions = self.section('8 方向空間搜尋表現分析 (Spatial Search Dashboard)')
        for axis, name, count, _, accuracy, rt, duration in direction_stats(formal):
            card = tk.Frame(directions, bg=CARD, padx=8, pady=7)
            card.grid(row=axis // 4, column=axis % 4, sticky='nsew', padx=3, pady=3)
            directions.columnconfigure(axis % 4, weight=1, uniform='direction')
            self.label(card, f'{ARROWS[axis]}  {name}', 11, bold=True, bg=CARD)
            tag, color = ('無測試', MUTED) if accuracy is None else (
                (f'{accuracy}% 優秀', GREEN) if accuracy >= 80 else
                (f'{accuracy}% 中等', AMBER) if accuracy >= 50 else (f'{accuracy}% 偏弱', RED)
            )
            self.label(card, tag, 9, bg=CARD, color=color)
            self.label(card, f'呈現次數：{count} 次', 9, bg=CARD, color=MUTED)
            self.label(card, '平均作答反應：' + (f'{rt} ms' if rt else '--'), 9, bg=CARD, color=MUTED)
            self.label(card, '刺激呈現時間：' + (f'{number_text(duration)} ms' if duration else '--'), 9, bg=CARD, color=MUTED)
        table_frame = tk.Frame(self.body, bg=PANEL)
        table_frame.pack(fill='x', pady=12)
        table = ttk.Treeview(table_frame, columns=TABLE_HEADERS, show='headings', height=min(8, len(trials)))
        vertical = ttk.Scrollbar(table_frame, orient='vertical', command=table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=table.xview)
        vertical.pack(side='right', fill='y')
        horizontal.pack(side='bottom', fill='x')
        table.pack(fill='x', expand=True)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for title, width in zip(TABLE_HEADERS, (48, 108, 95, 78, 76, 78, 76, 88, 78)):
            table.heading(title, text=title)
            table.column(title, width=width, minwidth=width, anchor='center')
        table.tag_configure('correct', foreground=GREEN)
        table.tag_configure('incorrect', foreground=RED)
        for trial in trials:
            axis, response = trial.get('peripheralAxis'), trial.get('peripheralResponse')
            table.insert('', 'end', values=(
                trial['trialNumber'], f"{number_text(trial['actualDurationMs'])} ms", f"{trial['refreshHz']} Hz",
                VEHICLES[trial['centralTarget']], '無' if axis is None else f'{ARROWS[axis]} {DIRECTIONS[axis]}',
                VEHICLES[trial['centralResponse']], '無' if response is None else f'{ARROWS[response]} {DIRECTIONS[response]}',
                f"{js_round(trial['responseTimeMs'])} ms", '✓ 成功' if trial['correct'] else '✗ 失敗',
            ), tags=('correct' if trial['correct'] else 'incorrect',))
        self.buttons(('重新開始', self.restart), ('下載 JSON (含軌跡)', self.save_json),
                     ('下載 CSV 臨床數據', self.choose_csv))

    def choose_csv(self):
        directory = filedialog.askdirectory(title='下載 CSV 臨床數據', parent=self.root, mustexist=True)
        if directory:
            self.save_csv(Path(directory))

    def save_csv(self, directory=None):
        when = self.finished if directory is None else datetime.now()
        try:
            paths = write_csvs(directory or downloads_path(), self.run_config, self.result, when)
        except OSError as error:
            self.status.configure(text=f'無法儲存 CSV。{error}', fg=AMBER)
            messagebox.showerror('無法儲存 CSV', f'{error}\n請使用「下載 CSV 臨床數據」選擇資料夾。', parent=self.root)
            return
        self.saved = True
        self.status.configure(text=f'已儲存 CSV　{paths[0].parent}', fg=TEXT)

    def save_json(self):
        day = datetime.now(timezone.utc).date().isoformat()
        name = filedialog.asksaveasfilename(title='下載 JSON (含軌跡)', defaultextension='.json',
                                            initialfile=f'peripheral_clinical_data_{day}.json', parent=self.root,
                                            filetypes=[('JSON', '*.json')])
        if not name:
            return
        try:
            write_json(Path(name), json_data(self.run_config, self.result, datetime.now()))
        except OSError as error:
            messagebox.showerror('無法儲存 JSON', str(error), parent=self.root)
            return
        self.saved = True
        messagebox.showinfo('下載 JSON (含軌跡)', f'已儲存至\n{name}', parent=self.root)

    def can_leave_results(self):
        return self.result is None or not self.result['trials'] or self.saved or messagebox.askyesno(
            '測驗結果尚未儲存', '測驗結果尚未儲存。要離開結果畫面嗎？', parent=self.root,
        )

    def restart(self):
        if self.can_leave_results():
            self.result = None
            self.settings()

    def close(self):
        if self.page_name == 'settings':
            self.persist()
        if self.can_leave_results():
            self.root.destroy()
