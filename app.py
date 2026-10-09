"""Rhino Converter desktop shell. Conversion is isolated in a child process."""
import json
import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from engine import FORMATS, output_name, ConversionError
import updater

BG = '#f3f6f8'
CARD = '#ffffff'
INK = '#192f32'
GREEN = '#14786b'
MUTED = '#617178'
FONT = 'Helvetica' if sys.platform == 'darwin' else 'Segoe UI'


def enable_display_scaling():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


class Converter(tk.Tk):
    def __init__(self):
        if os.name == 'nt':
            from windows_identity import configure_process
            configure_process()
        super().__init__()
        self.withdraw()
        self.title('Rhino Converter')
        icon_dir = Path(__file__).resolve().parent/'assets'
        self.app_icon = tk.PhotoImage(file=str(icon_dir/'RhinoConverter.png'))
        self.iconphoto(True, self.app_icon)
        if os.name == 'nt':
            # Assign this window's icon instead of only the global default.
            self.iconbitmap(str(icon_dir/'RhinoConverter.ico'))
        width = min(1200, int(self.winfo_screenwidth() * 0.85))
        height = min(860, int(self.winfo_screenheight() * 0.8))
        self.geometry('%sx%s' % (width, height))
        self.minsize(min(460, width), min(360, height))
        self.configure(bg=BG)
        # A withdrawn Tk window may still measure just one pixel wide.
        # Seed the first layout from the intended geometry, never that value.
        self.initial_canvas_width = max(100, width - 20)
        self.startup_callback = None
        self.show_loading_screen()
        self.files = []
        self.process = None
        self.job = None
        self.pending = []
        self.results = []
        self.last_folder = None
        self.started = 0
        self.closed = False
        self.review_source = None
        self.review_result = None
        self.poll_callback = None
        self.layout_callback = None
        self.drop_queue = queue.SimpleQueue()
        self.drop_handler = None
        self.drop_callback = None
        self.conversion_busy = False
        self.update_busy = False
        self.update_queue = queue.SimpleQueue()
        self.update_cancel = threading.Event()
        self.update_callback = None
        self.startup_update_callback = None
        self.available_release = None
        self.update_download = None
        self.app_version = updater.local_version()
        self.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10), background=BG, foreground=INK)
        style.configure('TButton', padding=(14, 9), borderwidth=0)
        style.configure('TButton', background='#e5ecef')
        style.map('TButton', background=[('active', '#d6e3e7')])
        style.configure('Primary.TButton', background=GREEN, foreground='white', font=(FONT, 11, 'bold'))
        style.map('Primary.TButton', background=[('active', '#106357'), ('disabled', '#d6e3e7')])
        style.configure('TCheckbutton', padding=4, background=CARD)
        style.map('TCheckbutton', background=[('active', '#f0f8f5')])
        style.configure('Selected.TCheckbutton', background='#e6f6f4', font=(FONT, 10, 'bold'))
        style.map('Selected.TCheckbutton', background=[('active', '#d8f0eb')])
        style.configure('TEntry', fieldbackground=CARD, bordercolor='#d5e0e5', padding=4)
        style.configure('TCombobox', fieldbackground=CARD, padding=4)
        style.configure('TProgressbar', troughcolor='#e1e9ed', background=GREEN, borderwidth=0)
        # The action area always stays on screen. Everything above it can
        # scroll when a small window or enlarged fonts need more room.
        self.footer = tk.Frame(self, bg=BG, padx=20, pady=12, highlightthickness=1, highlightbackground='#dce5e9')
        self.footer.pack(side='bottom', fill='x')
        viewport = tk.Frame(self, bg=BG)
        viewport.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(viewport, bg=BG, highlightthickness=0, width=1, height=1, takefocus=True)
        scrollbar = ttk.Scrollbar(viewport, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        shell = self.shell = tk.Frame(self.canvas, bg=BG, padx=20, pady=20)
        self.content_window = self.canvas.create_window(0, 0, window=shell, anchor='nw', width=self.initial_canvas_width)
        shell.bind('<Configure>', self.content_changed)
        self.canvas.bind('<Configure>', self.viewport_changed)
        self.bind_all('<MouseWheel>', self.scroll_wheel)
        self.bind_all('<Button-4>', self.scroll_wheel)
        self.bind_all('<Button-5>', self.scroll_wheel)
        self.bind_all('<FocusIn>', self.reveal_focus)
        self.canvas.bind('<Prior>', lambda event: self.canvas.yview_scroll(-1, 'pages'))
        self.canvas.bind('<Next>', lambda event: self.canvas.yview_scroll(1, 'pages'))
        self.wrap_labels = []
        tk.Label(shell, text='RHINO CONVERTER', font=(FONT, 10, 'bold'), fg=GREEN, bg=BG).pack(anchor='w')
        headline = tk.Label(shell, text='Convert your CAD files.', font=(FONT, 24, 'bold'), fg=INK, bg=BG, justify='left', anchor='w')
        headline.pack(fill='x', pady=(8, 5))
        subtitle = tk.Label(shell, text='Local conversion. No Rhino required. Your originals stay safe.', font=(FONT, 11), bg=BG, fg=MUTED, justify='left', anchor='w')
        subtitle.pack(fill='x')
        self.wrap_labels += [headline, subtitle]
        self.update_status = tk.StringVar(value='Version ' + self.app_version)
        update_label = tk.Label(shell, textvariable=self.update_status, font=(FONT, 9), bg=BG, fg=MUTED, anchor='w', justify='left')
        update_label.pack(fill='x', pady=(8, 0))
        self.wrap_labels.append(update_label)
        menu = tk.Menu(self)
        self.update_menu = tk.Menu(menu, tearoff=False)
        self.update_menu.add_command(label='Check for updates', command=self.check_for_updates)
        self.update_menu.add_command(label='Download update', command=self.download_update, state='disabled')
        self.update_menu.add_command(label='Install update', command=self.install_update, state='disabled')
        self.update_menu.add_command(label='Cancel download', command=self.update_cancel.set, state='disabled')
        menu.add_cascade(label='Updates', menu=self.update_menu)
        self.configure(menu=menu)
        self.body = tk.Frame(shell, bg=BG)
        self.body.pack(fill='x')
        self.left_column = tk.Frame(self.body, bg=BG)
        self.right_column = tk.Frame(self.body, bg=BG)
        self.body_columns = None
        file_card = self.section(self.left_column, '01   Rhino files')
        row = tk.Frame(file_card, bg=CARD)
        row.pack(fill='x')
        self.add_button = ttk.Button(row, text='+ Add files', command=self.add_files)
        self.add_button.pack(side='left')
        self.clear_button = ttk.Button(row, text='Clear list', command=self.clear_files)
        self.clear_button.pack(side='left', padx=8)
        self.file_label = tk.Label(row, text='0 files', bg=CARD, fg=MUTED)
        self.file_label.pack(side='right')
        self.listbox = tk.Listbox(file_card, height=5, bg='#f7fafb', fg=INK, selectbackground='#d5eee8', selectforeground=INK, relief='flat', highlightthickness=1, highlightbackground='#dde7eb', font=(FONT, 10))
        self.listbox.pack(fill='x', pady=(8, 0))
        self.empty_hint = tk.Label(self.listbox, text=('Choose Add files\nto select .3dm files' if sys.platform == 'darwin' else 'Drop .3dm files here\nor choose Add files'), bg='#f7fafb', fg=MUTED, font=(FONT, 11), justify='center')
        self.empty_hint.place(relx=0.5, rely=0.5, anchor='center')
        drop_hint = tk.Label(file_card, text=('Use Add files to choose one or more .3dm files.' if sys.platform == 'darwin' else 'Drop .3dm files anywhere in this window, or choose Add files.'), bg=CARD, fg=MUTED, font=(FONT, 9), justify='left', anchor='w')
        drop_hint.pack(fill='x', pady=(6, 0))
        self.wrap_labels.append(drop_hint)
        format_card = self.section(self.left_column, '02   Output formats')
        grid = self.format_grid = tk.Frame(format_card, bg=CARD)
        grid.pack(fill='x')
        self.format_vars = {}
        self.checks = []
        self.format_cells = []
        for i, (fmt, (label, detail)) in enumerate(FORMATS.items()):
            var = tk.BooleanVar(value=fmt == 'step')
            self.format_vars[fmt] = var
            cell = tk.Frame(grid, bg=CARD, padx=7, pady=8, highlightthickness=1, highlightbackground='#dfe7eb')
            cell.grid(row=i//3, column=i%3, sticky='nsew', padx=(0, 12), pady=(0, 8))
            button = ttk.Checkbutton(cell, text=label, variable=var, command=self.update_format_cards)
            button.pack(anchor='w')
            self.checks.append(button)
            description = tk.Label(cell, text=detail, bg=CARD, fg=MUTED, font=(FONT, 9), wraplength=220, justify='left', anchor='w')
            description.pack(fill='x', padx=5)
            self.format_cells.append((cell, description, button))
        hint = tk.Label(format_card, text='STEP / IGES / BREP preserve CAD geometry. STL / OBJ / PLY create meshes.', bg=CARD, fg=MUTED, font=(FONT, 9), justify='left', anchor='w')
        hint.pack(fill='x')
        self.wrap_labels.append(hint)
        save_card = self.section(self.right_column, '03   Save options')
        tk.Label(save_card, text='Destination folder', bg=CARD, fg=INK, font=(FONT, 10, 'bold')).pack(anchor='w', pady=(0, 5))
        row = tk.Frame(save_card, bg=CARD)
        row.pack(fill='x')
        self.destination = tk.StringVar(value=str(Path.home()/'Documents'/'Converted CAD'))
        self.dest_entry = ttk.Entry(row, textvariable=self.destination)
        self.dest_entry.pack(side='left', fill='x', expand=True, ipady=5)
        self.browse = ttk.Button(row, text='Browse', command=self.choose_folder)
        self.browse.pack(side='left', padx=(8, 0))
        name_row = tk.Frame(save_card, bg=CARD)
        name_row.pack(fill='x', pady=(8, 0))
        tk.Label(name_row, text='Output name:', bg=CARD, fg=INK).pack(side='left', padx=(0, 8))
        self.chosen_name = tk.StringVar()
        self.name_entry = ttk.Entry(name_row, textvariable=self.chosen_name)
        self.name_entry.pack(side='left', fill='x', expand=True, ipady=5)
        name_hint = tk.Label(save_card, text='Optional. Separate folders, with names like Fixture_STEP.step.', bg=CARD, fg=MUTED, font=(FONT, 9), justify='left', anchor='w')
        name_hint.pack(fill='x', pady=(4, 0))
        self.wrap_labels.append(name_hint)
        options = self.options_grid = tk.Frame(save_card, bg=CARD)
        options.pack(fill='x', pady=(8, 0))
        self.hidden = tk.BooleanVar(value=False)
        self.curves = tk.BooleanVar(value=True)
        self.checks += [ttk.Checkbutton(options, text='Include hidden geometry', variable=self.hidden), ttk.Checkbutton(options, text='Skip curves', variable=self.curves)]
        detail_row = tk.Frame(options, bg=CARD)
        tk.Label(detail_row, text='Mesh detail:', bg=CARD, fg=INK).pack(side='left')
        self.detail = ttk.Combobox(detail_row, state='readonly', values=['Fine (0.03 mm)', 'Standard (0.1 mm)', 'Coarse (0.5 mm)'], width=19)
        self.detail.current(1)
        self.detail.pack(side='left', padx=6)
        self.option_cells = [*self.checks[-2:], detail_row]
        actions = self.actions = tk.Frame(self.footer, bg=BG)
        actions.pack(fill='x', pady=(0, 8))
        self.convert_button = ttk.Button(actions, text='Convert files  →', style='Primary.TButton', command=self.start)
        self.cancel_button = ttk.Button(actions, text='Stop', command=self.cancel, state='disabled')
        self.open_button = ttk.Button(actions, text='Open results', command=self.open_results, state='disabled')
        self.skip_button = ttk.Button(actions, text='Skip this file', command=self.skip_review)
        self.progress = ttk.Progressbar(self.footer, maximum=100)
        self.progress.pack(fill='x')
        self.status = tk.StringVar(value='Ready. Original files are never overwritten.')
        self.status_label = tk.Label(self.footer, textvariable=self.status, bg=BG, fg=GREEN, font=(FONT, 10), anchor='w', justify='left')
        self.status_label.pack(fill='x', pady=(6, 0))
        activity_card = self.section(self.right_column, 'Conversion details')
        self.outcome = tk.StringVar(value='Ready to convert')
        outcome_label = tk.Label(activity_card, textvariable=self.outcome, bg=CARD, fg=GREEN, font=(FONT, 13, 'bold'), anchor='w', justify='left')
        outcome_label.pack(fill='x', pady=(0, 8))
        self.wrap_labels.append(outcome_label)
        self.log = tk.Text(activity_card, height=5, wrap='word', relief='flat', bg='#f4f8fa', fg=INK, font=(FONT, 9), padx=12, pady=10, state='disabled')
        self.log.pack(fill='both', expand=True)
        self.write_log('Prototype: six export formats. Complex models should be checked before production use.\nNative DWG, Parasolid, SAT and SolidWorks output are not supported in this free version.')
        self.update_format_cards()
        self.layout()
        self.startup_callback = self.after_idle(self.finish_startup)

    def show_loading_screen(self):
        self.splash = tk.Toplevel(self)
        self.splash.withdraw()
        self.splash.overrideredirect(True)
        self.splash.configure(bg=GREEN)
        self.splash.attributes('-topmost', True)
        panel = tk.Frame(self.splash, bg=BG, padx=32, pady=28)
        panel.pack(fill='both', expand=True, padx=1, pady=1)
        tk.Label(panel, text='RHINO CONVERTER', font=(FONT, 16, 'bold'), bg=BG, fg=GREEN).pack(anchor='w')
        tk.Label(panel, text='Preparing converter…', font=(FONT, 11), bg=BG, fg=INK).pack(anchor='w', pady=(12, 16))
        self.loading_progress = ttk.Progressbar(panel, mode='indeterminate', length=290)
        self.loading_progress.pack(fill='x')
        self.loading_progress.start(15)
        self.splash.update_idletasks()
        width, height = self.splash.winfo_reqwidth(), self.splash.winfo_reqheight()
        left = max(0, (self.winfo_screenwidth() - width)//2)
        top = max(0, (self.winfo_screenheight() - height)//2)
        self.splash.geometry('%sx%s+%s+%s' % (width, height, left, top))
        self.splash.deiconify()
        self.splash.update_idletasks()

    def finish_startup(self):
        self.startup_callback = None
        if self.closed:
            return
        self.update_idletasks()
        self.layout()
        self.update_idletasks()
        self.deiconify()
        if os.name == 'nt':
            # Tk has now mapped the native wrapper window used by Windows.
            self.iconbitmap(str(Path(__file__).resolve().parent/'assets/RhinoConverter.ico'))
        # Resolve the real viewport after mapping, before the next screen paint.
        self.update_idletasks()
        self.layout()
        self.update_idletasks()
        self.loading_progress.stop()
        self.splash.destroy()
        self.splash = None
        self.enable_drops()
        self.startup_update_callback = self.after(750, self.startup_update_check)

    def startup_update_check(self):
        self.startup_update_callback = None
        try:
            updater.configuration()
        except (OSError, ValueError, updater.UpdateError):
            self.update_status.set('Version ' + self.app_version + ' · Updates not configured')
            return
        self.check_for_updates(manual=False)

    def check_for_updates(self, manual=True):
        if self.update_busy:
            return
        try:
            config = updater.configuration()
            target = updater.platform_id()
        except (OSError, ValueError, updater.UpdateError) as exc:
            if manual:
                messagebox.showinfo('Updates', 'Updates are not configured for this build. The publisher must configure the GitHub repository and release signing before building the app.\n\n' + str(exc))
            return
        self.update_busy = True
        self.update_cancel.clear()
        self.update_menu.entryconfigure(0, state='disabled')
        self.update_menu.entryconfigure(1, state='disabled')
        self.update_menu.entryconfigure(2, state='disabled')
        self.update_status.set('Checking for updates…')
        def task():
            try:
                release = updater.check_release(config, self.app_version, target)
                self.update_queue.put(('checked', release))
            except Exception as exc:
                self.update_queue.put(('error', str(exc)))
        threading.Thread(target=task, daemon=True).start()
        self.schedule_update_poll()

    def download_update(self):
        if self.update_busy or self.available_release is None:
            return
        release = self.available_release
        directory = Path(tempfile.mkdtemp(prefix='rhino-converter-update-'))
        destination = directory/release.name
        self.update_busy = True
        self.update_cancel.clear()
        self.update_menu.entryconfigure(0, state='disabled')
        self.update_menu.entryconfigure(1, state='disabled')
        self.update_menu.entryconfigure(3, state='normal')
        self.update_status.set('Downloading update…')
        def task():
            try:
                updater.download_release(release, destination,
                    lambda value: self.update_queue.put(('progress', value)), self.update_cancel)
                self.update_queue.put(('downloaded', destination))
            except Exception as exc:
                self.update_queue.put(('error', str(exc)))
        threading.Thread(target=task, daemon=True).start()
        self.schedule_update_poll()

    def schedule_update_poll(self):
        if self.update_callback is None and not self.closed:
            self.update_callback = self.after(100, self.poll_updates)

    def poll_updates(self):
        self.update_callback = None
        if self.closed:
            return
        while not self.update_queue.empty():
            kind, value = self.update_queue.get()
            if kind == 'progress':
                self.update_status.set('Downloading update… %s%%' % int(value*100))
                continue
            self.update_busy = False
            self.update_menu.entryconfigure(0, state='normal')
            self.update_menu.entryconfigure(3, state='disabled')
            if kind == 'checked':
                self.available_release = value
                self.update_download = None
                self.update_status.set('Version '+self.app_version+' · '+('Update '+value.version+' available — use Updates → Download update' if value else 'Up to date'))
            elif kind == 'downloaded':
                self.update_download = value
                self.update_status.set('Verified update ready — use Updates → Install update')
            else:
                self.update_status.set('Update unavailable. Conversion is still available.')
                self.write_log('Update: '+value)
            self.update_menu.entryconfigure(1, state='normal' if self.available_release and not self.update_download else 'disabled')
            self.update_menu.entryconfigure(2, state='normal' if self.update_download else 'disabled')
        if self.update_busy:
            self.schedule_update_poll()

    def install_update(self):
        if self.update_busy or self.update_download is None:
            return
        if self.conversion_busy or self.process or self.pending or self.review_source:
            messagebox.showinfo('Finish conversion first', 'Finish or stop the conversion before installing the update.')
            return
        if not messagebox.askyesno('Install verified update?', 'Rhino Converter will close, install the update, and reopen. Your model files will stay unchanged.'):
            return
        try:
            if sys.platform == 'win32':
                updater.launch_windows_update(self.update_download, self.available_release)
            elif sys.platform == 'darwin':
                updater.launch_mac_update(self.update_download, self.available_release)
            else:
                raise updater.UpdateError('Install updates on Windows or Mac.')
        except Exception as exc:
            messagebox.showerror('Update was not installed', str(exc))
            return
        self.destroy()

    def enable_drops(self):
        if os.name != 'nt' or self.closed:
            return
        try:
            from windows_drop import WindowsFileDrop
            self.drop_handler = WindowsFileDrop(self, self.drop_queue.put)
            self.consume_drops()
        except (OSError, AttributeError) as exc:
            self.write_log('Drag-and-drop is unavailable: ' + str(exc) + '. Add files still works.')

    def consume_drops(self):
        self.drop_callback = None
        if self.closed:
            return
        while not self.drop_queue.empty():
            self.add_paths(self.drop_queue.get())
        self.drop_callback = self.after(100, self.consume_drops)

    def viewport_changed(self, event):
        if event.width < 100:
            return
        self.canvas.itemconfigure(self.content_window, width=event.width)
        if self.layout_callback is None:
            self.layout_callback = self.after_idle(self.layout)

    def content_changed(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def layout(self):
        self.layout_callback = None
        measured_width = self.canvas.winfo_width()
        width = (measured_width if measured_width >= 100 else self.initial_canvas_width) - 40
        columns = 2 if width >= 1000 else 1
        if columns != self.body_columns:
            self.left_column.grid(row=0, column=0, sticky='new', padx=(0, 16) if columns == 2 else 0)
            self.right_column.grid(row=0 if columns == 2 else 1, column=1 if columns == 2 else 0, sticky='new')
            self.body.columnconfigure(0, weight=1, uniform='cards')
            self.body.columnconfigure(1, weight=1 if columns == 2 else 0, uniform='cards' if columns == 2 else '')
            self.body_columns = columns
        card_width = (width - 16)//2 if columns == 2 else width
        for label in self.wrap_labels:
            label.configure(wraplength=width if label.master is self.shell else max(40, card_width - 34))
        width = max(40, card_width - 34)  # card padding and border
        self.empty_hint.configure(wraplength=width - 20)
        # Use font/widget measurements rather than fixed screen breakpoints.
        min_cell = max(145, max(button.winfo_reqwidth() + 35 for _, _, button in self.format_cells))
        columns = min(3, max(1, width // min_cell))
        for column in range(3):
            self.format_grid.columnconfigure(column, weight=1 if column < columns else 0, minsize=0)
        for i, (cell, label, _) in enumerate(self.format_cells):
            cell.grid(row=i//columns, column=i%columns, sticky='nsew', padx=(0, 12), pady=(0, 10))
            label.configure(wraplength=max(40, width//columns - 40))
        option_width = max(cell.winfo_reqwidth() + 14 for cell in self.option_cells)
        option_columns = min(3, max(1, width // option_width))
        for column in range(3):
            self.options_grid.columnconfigure(column, weight=0, minsize=0)
        for i, cell in enumerate(self.option_cells):
            cell.grid(row=i//option_columns, column=i%option_columns, sticky='w', padx=(0, 14), pady=(0, 5))
        footer_width = self.footer.winfo_width()
        action_width = (footer_width if footer_width >= 100 else self.initial_canvas_width) - 40
        required = sum(button.winfo_reqwidth() for button in [self.convert_button, self.cancel_button, self.open_button]) + 24
        self.actions.columnconfigure(0, weight=1)
        self.actions.columnconfigure(1, weight=0)
        self.actions.columnconfigure(2, weight=0)
        pair_fits = self.convert_button.winfo_reqwidth() + self.cancel_button.winfo_reqwidth() + 16 <= action_width
        self.convert_button.grid(row=0, column=0, sticky='w')
        self.cancel_button.grid(row=0 if pair_fits else 1, column=1 if pair_fits else 0, sticky='w', padx=8 if pair_fits else 0, pady=0 if pair_fits else (6, 0))
        self.open_button.grid(row=0 if required <= action_width else (1 if pair_fits else 2), column=2 if required <= action_width else 0, sticky='e' if required <= action_width else 'w', pady=(0, 0) if required <= action_width else (6, 0))
        self.status_label.configure(wraplength=action_width)
        if self.review_source:
            self.skip_button.grid(row=3, column=0, sticky='w', pady=(6, 0))
        else:
            self.skip_button.grid_remove()
        self.content_changed()

    def scroll_wheel(self, event):
        # List and log widgets retain their own scrolling behavior.
        if event.widget in (self.listbox, self.log):
            return
        first, last = self.canvas.yview()
        if first == 0 and last == 1:
            return
        if getattr(event, 'num', None) in (4, 5):
            units = -3 if event.num == 4 else 3
        else:
            delta = getattr(event, 'delta', 0)
            units = -max(1, abs(delta)//120) if delta > 0 else max(1, abs(delta)//120)
        self.canvas.yview_scroll(units, 'units')
        return 'break'

    def reveal_focus(self, event):
        widget = event.widget
        parent = widget
        while parent is not None and parent is not self.shell:
            parent = getattr(parent, 'master', None)
        if parent is None:
            return
        top = widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        region = self.canvas.bbox('all')
        if region and region[3] > 0:
            current = self.canvas.canvasy(0)
            if top < 0:
                self.canvas.yview_moveto(max(0, (current + top - 10)/region[3]))
            elif bottom > self.canvas.winfo_height():
                self.canvas.yview_moveto((current + bottom-self.canvas.winfo_height()+10)/region[3])

    def section(self, parent, text):
        card = tk.Frame(parent, bg=CARD, padx=16, pady=14, highlightthickness=1, highlightbackground='#dfe7eb')
        card.pack(fill='x', pady=(16, 0))
        tk.Label(card, text=text, bg=CARD, fg=INK, font=(FONT, 11, 'bold')).pack(anchor='w', pady=(0, 10))
        return card

    def update_format_cards(self):
        for (fmt, var), (cell, label, button) in zip(self.format_vars.items(), self.format_cells):
            selected = var.get()
            background = '#e6f6f4' if selected else CARD
            cell.configure(bg=background, highlightbackground=GREEN if selected else '#dfe7eb')
            label.configure(bg=background)
            button.configure(style='Selected.TCheckbutton' if selected else 'TCheckbutton')

    def write_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def add_files(self):
        paths = filedialog.askopenfilenames(title='Choose Rhino files', filetypes=[('Rhino model', '*.3dm')])
        self.add_paths(paths)

    def add_paths(self, paths):
        if self.process or self.pending or self.review_source:
            self.write_log('Wait for this batch to finish, or press Stop, before adding files.')
            return
        known = {os.path.normcase(str(Path(path).resolve())) for path in self.files}
        rejected = []
        for path in paths:
            candidate = Path(path)
            if not candidate.is_file() or candidate.suffix.lower() != '.3dm':
                rejected.append(candidate.name)
                continue
            key = os.path.normcase(str(candidate.resolve()))
            if key not in known:
                known.add(key)
                self.files.append(str(candidate.resolve()))
                self.listbox.insert('end', candidate.name)
        self.file_label.configure(text='%s files' % len(self.files))
        if self.files:
            self.empty_hint.place_forget()
        if rejected:
            self.write_log('Only .3dm files can be added. Skipped: ' + ', '.join(rejected))

    def clear_files(self):
        self.files.clear()
        self.listbox.delete(0, 'end')
        self.empty_hint.place(relx=0.5, rely=0.5, anchor='center')
        self.file_label.configure(text='0 files')

    def choose_folder(self):
        folder = filedialog.askdirectory(title='Choose export destination')
        if folder:
            self.destination.set(folder)

    def set_busy(self, busy):
        self.conversion_busy = busy
        for widget in [self.add_button, self.clear_button, self.browse, self.dest_entry, self.name_entry, self.convert_button, *self.checks]:
            widget.configure(state='disabled' if busy else 'normal')
        self.detail.configure(state='disabled' if busy else 'readonly')
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def start(self):
        if self.review_source:
            source = self.review_source
            self.review_source = None
            self.review_result = None
            self.convert_button.configure(text='Convert files  →', state='disabled')
            self.layout()
            self.write_log('Convert anyway approved: exporting supported geometry from a copy; skipped objects will be listed in the report.')
            self.next_job(source=source, allow_partial=True)
            return
        formats = [f for f, v in self.format_vars.items() if v.get()]
        if not self.files or not formats or not self.destination.get().strip():
            messagebox.showinfo('Choose files and formats', 'Add a .3dm file, select at least one output format, and choose a destination.')
            return
        self.batch_name = self.chosen_name.get().strip()
        if self.batch_name:
            try:
                for source in self.files:
                    output_name(self.batch_name if len(self.files) == 1 else self.batch_name + '-' + Path(source).stem)
            except ConversionError as exc:
                messagebox.showinfo('Choose another output name', str(exc))
                return
        self.settings = {'destination': self.destination.get(), 'formats': formats, 'options': {'include_hidden': self.hidden.get(), 'exclude_curves': self.curves.get(), 'deviation': [0.03, 0.1, 0.5][self.detail.current()]}}
        self.pending = list(self.files)
        self.results = []
        self.total = len(self.pending)
        self.set_busy(True)
        self.next_job()

    def next_job(self, source=None, allow_partial=False):
        if source is None and not self.pending:
            self.finish()
            return
        if source is None:
            source = self.pending.pop(0)
        self.work = tempfile.TemporaryDirectory(prefix='rhino-converter-')
        self.job = Path(self.work.name)/'job.json'
        self.job.write_text(json.dumps({'source': source, **self.settings,
                                      'options': {**self.settings['options'], 'allow_partial': allow_partial,
                                                  'output_name': (self.batch_name if self.total == 1 else self.batch_name + '-' + Path(source).stem) if self.batch_name else None}}), encoding='utf-8')
        self.current = source
        self.write_log('Converting ' + Path(source).name)
        self.status.set('Starting conversion engine…')
        self.outcome.set('Converting…\n' + Path(source).name)
        self.started = time.monotonic()
        command = [sys.executable, '--worker', str(self.job)] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--worker', str(self.job)]
        try:
            self.worker_log = (Path(self.work.name)/'worker.log').open('wb')
            self.process = subprocess.Popen(command, stdout=self.worker_log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.schedule_poll()
        except Exception as exc:
            self.write_log('Could not start: ' + str(exc))
            self.cleanup()
            self.pending.clear()
            self.finish()

    def poll(self):
        self.poll_callback = None
        if not self.process or self.closed:
            return
        try:
            state = json.loads(self.job.with_suffix('.state.json').read_text(encoding='utf-8'))
            self.progress['value'] = 100*(len(self.results)+state['progress'])/self.total
            self.status.set(state['message'])
        except (OSError, ValueError):
            pass
        if time.monotonic()-self.started > 600:
            self.write_log('Stopped: this file exceeded the ten minute conversion limit.')
            self.process.kill()
        if self.process.poll() is None:
            self.schedule_poll()
            return
        result_file = self.job.with_suffix('.result.json')
        try:
            result = json.loads(result_file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            result = {'status': 'failed', 'outputs': [], 'error': 'The conversion engine exited unexpectedly. No successful result was reported.'}
        if result.get('error'):
            self.write_log(result['error'])
        if result.get('needs_confirmation'):
            self.review_source = self.current
            self.review_result = result
            self.cleanup()
            self.convert_button.configure(text='Convert anyway  →', state='normal')
            self.status.set('Review the skipped objects above. Convert anyway, skip this file, or stop.')
            self.outcome.set('Review skipped objects')
            self.layout()
            return
        self.results.append(result)
        for output in result.get('outputs', []):
            self.write_log('Saved ' + Path(output['path']).name)
        for fmt, error in result.get('format_errors', {}).items():
            self.write_log(fmt.upper() + ': ' + error)
        for warning in result.get('warnings', []):
            self.write_log(warning)
        if result.get('folder'):
            self.last_folder = result['folder']
            self.open_button.configure(state='normal')
            self.write_log('Report: ' + str(Path(result['folder'])/'conversion-report.json'))
        self.cleanup()
        self.next_job()

    def cleanup(self):
        if self.poll_callback is not None:
            self.after_cancel(self.poll_callback)
            self.poll_callback = None
        self.process = None
        if hasattr(self, 'worker_log'):
            self.worker_log.close()
        if hasattr(self, 'work'):
            self.work.cleanup()

    def schedule_poll(self):
        if self.poll_callback is None:
            self.poll_callback = self.after(250, self.poll)

    def finish(self):
        self.set_busy(False)
        self.convert_button.configure(text='Convert files  →')
        outputs = sum(len(r.get('outputs', [])) for r in self.results)
        failures = sum(r.get('status') != 'complete' for r in self.results)
        self.progress['value'] = 100 if self.results else 0
        self.status.set('%s output files saved. %s source files need attention.' % (outputs, failures))
        self.outcome.set(('Conversion complete' if not failures else 'Conversion needs attention') + '\n%s files saved' % outputs if self.results else 'Ready to convert')

    def cancel(self):
        self.pending.clear()
        self.review_source = None
        self.review_result = None
        if self.process:
            self.process.kill()
            self.process.wait()
            self.write_log('Conversion stopped. Any already completed exports remain in the destination.')
            self.cleanup()
        self.finish()
        if not self.closed:
            self.layout()

    def skip_review(self):
        if not self.review_source:
            return
        self.write_log('Skipped ' + Path(self.review_source).name)
        self.results.append(self.review_result)
        self.review_source = None
        self.review_result = None
        self.convert_button.configure(text='Convert files  →', state='disabled')
        self.layout()
        self.next_job()

    def open_results(self):
        if self.last_folder:
            if os.name == 'nt':
                os.startfile(self.last_folder)
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', self.last_folder])

    def close(self):
        if self.process and not messagebox.askyesno('Stop conversion?', 'A conversion is running. Stop it and close the app?'):
            return
        self.closed = True
        self.cancel()
        self.destroy()

    def destroy(self):
        self.closed = True
        self.update_cancel.set()
        for attribute in ('startup_callback', 'layout_callback', 'update_callback', 'startup_update_callback'):
            callback = getattr(self, attribute, None)
            if callback is not None:
                self.after_cancel(callback)
                setattr(self, attribute, None)
        if self.splash is not None:
            self.loading_progress.stop()
            self.splash.destroy()
            self.splash = None
        if self.drop_callback is not None:
            self.after_cancel(self.drop_callback)
            self.drop_callback = None
        if self.drop_handler is not None:
            self.drop_handler.close()
            self.drop_handler = None
        super().destroy()


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--register-shortcuts' and os.name == 'nt':
        from windows_identity import register_shortcut
        for path in sys.argv[2:]:
            register_shortcut(path)
    elif len(sys.argv) == 3 and sys.argv[1] == '--apply-mac-update':
        from mac_update import apply_update
        raise SystemExit(apply_update(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == '--worker':
        from engine import worker
        worker(sys.argv[2])
    else:
        enable_display_scaling()
        Converter().mainloop()
