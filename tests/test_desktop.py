"""Real Tk layout and event-loop checks; skipped when no display is available."""
import os
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Converter


class Desktop(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Requires native Windows taskbar APIs')
    def test_windows_taskbar_uses_converter_identity(self):
        from windows_identity import APP_ID, current_process_id
        self.assertEqual(current_process_id(), APP_ID)

    @unittest.skipUnless(os.name == 'nt', 'Requires native Windows icon APIs')
    def test_windows_window_icons_match_converter_artwork_after_startup(self):
        from windows_icon_support import u, pixels
        self.settle()
        window = u.GetParent(self.app.winfo_id()) or self.app.winfo_id()
        path = str(Path(__file__).resolve().parents[1]/'assets/RhinoConverter.ico')
        for mode, size in ((0, 16), (1, 32)):
            with self.subTest(size=size):
                actual = u.SendMessageW(window, 0x7f, mode, 0)
                expected = u.LoadImageW(None, path, 1, size, size, 0x10)
                try:
                    self.assertTrue(actual, 'Windows has no custom window icon')
                    self.assertTrue(expected, 'Windows could not load converter artwork')
                    self.assertEqual(pixels(actual, size), pixels(expected, size))
                finally:
                    if expected:
                        u.DestroyIcon(expected)

    def setUp(self):
        try:
            self.app = Converter()
            self.startup_state = self.app.state()
            self.splash_visible = bool(self.app.splash.winfo_ismapped())
            self.initial_wraps = [int(label.cget('wraplength')) for label in self.app.wrap_labels]
            self.app.update()
        except tk.TclError as exc:
            self.skipTest('No Tk display: ' + str(exc))
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        if hasattr(self, 'app'):
            self.app.closed = True
            self.app.cancel()
            self.app.destroy()
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def settle(self):
        self.app.update()
        self.app.layout()
        self.app.update()

    def pump_until(self, condition):
        deadline = time.monotonic() + 30
        while not condition():
            self.app.update()
            if time.monotonic() > deadline:
                self.fail('Desktop conversion did not reach the expected state.')
            time.sleep(0.01)

    def test_loading_screen_hides_unfinished_layout(self):
        self.assertEqual(self.startup_state, 'withdrawn')
        self.assertTrue(self.splash_visible)
        self.assertGreater(min(self.initial_wraps), 100)
        self.assertEqual(self.app.state(), 'normal')
        self.assertIsNone(self.app.splash)
        self.assertTrue(self.app.convert_button.winfo_ismapped())
        self.assertGreater(self.app.canvas.winfo_width(), 100)

    def test_small_windows_keep_actions_visible_and_forms_scroll(self):
        for width, height in [(1200,860),(960,820),(640,480),(480,420),(460,360)]:
            self.app.geometry('%sx%s' % (width,height))
            self.settle()
            # Window managers may clamp the requested size to the CI display.
            # Check the layout and controls against the actual client area.
            width, height = self.app.winfo_width(), self.app.winfo_height()
            self.assertEqual(self.app.body_columns, 2 if self.app.canvas.winfo_width() >= 1040 else 1)
            for column in (self.app.left_column, self.app.right_column):
                self.assertLessEqual(column.winfo_x()+column.winfo_width(), self.app.body.winfo_width())
            for button in [self.app.convert_button,self.app.cancel_button,self.app.open_button]:
                self.assertTrue(button.winfo_ismapped())
                left = button.winfo_rootx() - self.app.winfo_rootx()
                top = button.winfo_rooty() - self.app.winfo_rooty()
                self.assertGreaterEqual(left,0)
                self.assertLessEqual(left+button.winfo_width(),width)
                self.assertGreaterEqual(top,0)
                self.assertLessEqual(top+button.winfo_height(),height)
            for cell, _, _ in self.app.format_cells:
                self.assertLessEqual(cell.winfo_x()+cell.winfo_width(),self.app.format_grid.winfo_width())
        self.assertLess(self.app.canvas.yview()[1],1)
        self.app.canvas.yview_moveto(1)
        self.settle()
        self.assertGreater(self.app.canvas.yview()[0],0)
        self.assertTrue(self.app.curves.get())
        step_cell = self.app.format_cells[0][0]
        self.assertEqual(step_cell.cget('background'), '#e6f6f4')
        self.app.format_vars['step'].set(False)
        self.app.update_format_cards()
        self.assertEqual(step_cell.cget('background'), '#ffffff')

    def test_worker_remains_responsive_and_convert_anyway_resumes(self):
        import rhino3dm as r3
        source=Path(self.tmp.name)/'review.3dm'
        model=r3.File3dm();model.Settings.ModelUnitSystem=r3.UnitSystem.Millimeters
        model.Objects.AddBrep(r3.BoundingBox(r3.Point3d(0,0,0),r3.Point3d(1,2,3)).ToBrep())
        cloud=r3.PointCloud();cloud.Add(r3.Point3d(9,9,9))
        model.Objects.AddPointCloud(cloud)
        model.Write(str(source),6)
        self.app.files=[str(source)]
        self.app.destination.set(str(Path(self.tmp.name)/'out'))
        ticks=[]
        def heartbeat():
            ticks.append(time.monotonic())
            if not self.app.closed:
                self.app.after(20,heartbeat)
        heartbeat()
        self.app.start()
        self.assertIn('Converting', self.app.outcome.get())
        self.app.geometry('480x420')
        self.pump_until(lambda:self.app.review_source is not None)
        self.assertGreater(len(ticks),2)
        self.assertEqual(self.app.convert_button.cget('text'),'Convert anyway  →')
        self.assertTrue(self.app.skip_button.winfo_ismapped())
        self.assertEqual(self.app.outcome.get(), 'Review skipped objects')
        self.app.start()
        self.pump_until(lambda:bool(self.app.results) and self.app.process is None)
        self.assertEqual(self.app.results[0]['status'],'partial')
        self.assertEqual(len(self.app.results[0]['outputs']),1)
        self.assertIsNone(self.app.review_source)
        self.assertIsNone(self.app.poll_callback)
        self.assertIn('needs attention',self.app.outcome.get())

    def test_drop_list_filters_files_and_deduplicates(self):
        root=Path(self.tmp.name)
        one=root/'My lamp.3dm';one.write_bytes(b'placeholder')
        other=root/'other.3DM';other.write_bytes(b'placeholder')
        wrong=root/'notes.txt';wrong.write_text('not a model')
        self.app.add_paths([str(one),str(other),str(wrong),str(one),str(root/'missing.3dm')])
        self.assertEqual(len(self.app.files),2)
        self.assertEqual(self.app.listbox.size(),2)
        self.assertFalse(self.app.empty_hint.winfo_ismapped())
        self.assertIn('Only .3dm files',self.app.log.get('1.0','end'))
        self.app.clear_files()
        self.app.update()
        self.assertTrue(self.app.empty_hint.winfo_ismapped())

    def test_save_defaults_and_folder_picker_for_all_modes(self):
        self.assertTrue(self.app.new_folder.get())
        self.assertTrue(self.app.source_folder.get())
        self.assertEqual(str(self.app.dest_entry.cget('state')), 'disabled')
        self.app.files = [str(Path(self.tmp.name)/'sample.3dm')]
        chosen = str(Path(self.tmp.name)/'chosen')
        for source_folder in (True, False):
            for new_folder in (True, False):
                with self.subTest(source_folder=source_folder, new_folder=new_folder):
                    self.app.source_folder.set(source_folder)
                    self.app.new_folder.set(new_folder)
                    self.app.destination.set('')
                    self.app.update_save_options()
                    with patch('app.filedialog.askdirectory', return_value=chosen) as choose, \
                         patch.object(self.app, 'next_job') as launch:
                        self.app.start()
                    self.assertEqual(choose.call_count, 0 if source_folder else 1)
                    launch.assert_called_once()
                    self.assertEqual(self.app.settings['options']['source_folder'], source_folder)
                    self.assertEqual(self.app.settings['options']['new_folder'], new_folder)
                    self.app.set_busy(False)
                    expected = 'disabled' if source_folder else 'normal'
                    self.assertEqual(str(self.app.dest_entry.cget('state')), expected)

    def test_cancel_destination_picker_does_not_start_conversion(self):
        self.app.files = [str(Path(self.tmp.name)/'sample.3dm')]
        for new_folder in (True, False):
            with self.subTest(new_folder=new_folder):
                self.app.source_folder.set(False)
                self.app.new_folder.set(new_folder)
                with patch('app.filedialog.askdirectory', return_value='') as choose, \
                     patch.object(self.app, 'next_job') as launch:
                    self.app.start()
                choose.assert_called_once()
                launch.assert_not_called()
                self.assertFalse(self.app.conversion_busy)
                self.assertEqual(self.app.results, [])

    def test_unchecking_source_prompts_and_batch_uses_each_source_folder(self):
        with patch('app.filedialog.askdirectory', return_value=self.tmp.name) as choose:
            self.app.source_folder_check.invoke()
        choose.assert_called_once()
        self.assertEqual(self.app.destination.get(), self.tmp.name)
        self.app.source_folder_check.invoke()
        import rhino3dm as r3
        sources = []
        for name in ('first', 'second'):
            parent = Path(self.tmp.name)/name
            parent.mkdir()
            source = parent/'sample.3dm'
            model = r3.File3dm()
            model.Settings.ModelUnitSystem = r3.UnitSystem.Millimeters
            model.Objects.AddBrep(r3.BoundingBox(r3.Point3d(0,0,0), r3.Point3d(1,2,3)).ToBrep())
            self.assertTrue(model.Write(str(source), 6))
            sources.append(source)
        self.app.files = list(map(str, sources))
        self.app.start()
        self.pump_until(lambda:len(self.app.results) == 2 and self.app.process is None)
        for source, result in zip(sources, self.app.results):
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(Path(result['folder']), source.parent/'sample')
            self.assertEqual(Path(result['report_path']).parent, source.parent/'sample')


if __name__=='__main__': unittest.main()
