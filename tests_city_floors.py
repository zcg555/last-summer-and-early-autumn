"""Offline regression tests against the actual recovered pricing modules."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from module_runtime import install
install()
from charter_quotes import floor_settings as fs
from charter_quotes.quote_fields import floor_value, FLOORS, PACKAGES
from charter_quotes.core import SHANGHAI
from charter_quotes.auto_reprice import plan_today
from hourly_reprice import resources_today

class CityFloors(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent/'test-data')
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': self.temp.name})
        self.env.start()
        fs._active = None
        self.values = fs.defaults()
    def tearDown(self):
        fs._active = None
        self.env.stop()
        self.temp.cleanup()
    def test_legacy_migrates_independently_without_overwriting(self):
        legacy = fs.settings_path().with_name('floor-prices.json')
        legacy.parent.mkdir(parents=True)
        table = copy.deepcopy(fs.DEFAULT_FLOORS)
        table['经济5座'][0] = 333
        content = json.dumps(dict(version=1, packages=PACKAGES, floors=table))
        legacy.write_text(content, encoding='utf8')
        values = fs.load()
        self.assertEqual(values['杭州']['经济5座'][0], 333)
        values['上海']['经济5座'][0] = 444
        self.assertEqual(values['杭州']['经济5座'][0], 333)
        fs.save_city('上海', values['上海'])
        self.assertEqual(fs.load()['上海']['经济5座'][0], 444)
        self.assertEqual(fs.load()['杭州']['经济5座'][0], 333)
        self.assertEqual(legacy.read_text(encoding='utf8'), content)
    def test_save_each_city_and_restart(self):
        self.values['上海']['经济5座'][0] = 900
        self.values['杭州']['经济5座'][0] = 700
        fs.save_city('上海', self.values['上海'])
        fs.save_city('杭州', self.values['杭州'])
        fs.activate(fs.load())
        for city, expected in [('上海',900),('杭州',700)]:
            self.assertEqual(floor_value(dict(city=city,vehicle_name='经济5座',hours=4,kilometers=50)),expected)
    def test_all_mapped_resources_use_own_city_for_raise(self):
        for city, amount in [('上海',2101),('杭州',2302)]:
            for vehicle in self.values[city]:
                self.values[city][vehicle] = [amount] * len(PACKAGES)
        fs.activate(self.values)
        resources = resources_today(list(FLOORS))
        self.assertEqual(len(resources),90)
        self.assertEqual(sum(r['city']=='上海' for r in resources),50)
        self.assertEqual(sum(r['city']=='杭州' for r in resources),40)
        for r in resources:
            expected = 2101 if r['city']=='上海' else 2302
            self.assertEqual(r['floor_price'], expected)
            self.assertEqual(max(2000,r['floor_price']),expected)
    def test_real_planner_uses_each_floor(self):
        self.values['上海']['经济5座'][0] = 900
        self.values['杭州']['经济5座'][0] = 700
        fs.activate(self.values)
        now = datetime.now(SHANGHAI)
        rows = [dict(city=c,vehicle_name='经济5座',hours=4,kilometers=50,
                     currency='CNY',use_date=now.date().isoformat(),is_mock=False,
                     price_minor=50000,collected_at=now.isoformat()) for c in fs.CITIES]
        result = plan_today(rows,now=now)
        self.assertEqual(len(result['ready']),2, result)
        self.assertEqual([r['target_price'] for r in result['ready']], [900,700])
    def test_snapshot_does_not_change_after_disk_save_or_input_edit(self):
        fs.activate(self.values)
        old = floor_value(dict(city='上海',vehicle_name='经济5座',hours=4,kilometers=50))
        self.values['上海']['经济5座'][0] = 999
        fs.save(self.values)
        self.assertEqual(floor_value(dict(city='上海',vehicle_name='经济5座',hours=4,kilometers=50)),old)
        self.assertEqual(FLOORS,fs.DEFAULT_FLOORS)
    def test_invalid_values_do_not_replace_saved_file(self):
        fs.save(self.values)
        before = fs.settings_path().read_bytes()
        for invalid in ('', '0', '-1', '1.2', True, 1000001):
            v = copy.deepcopy(self.values)
            v['杭州']['经济5座'][0] = invalid
            with self.assertRaises(ValueError): fs.save(v)
            self.assertEqual(fs.settings_path().read_bytes(),before)
    def test_corrupt_new_file_does_not_fall_back_to_legacy(self):
        fs.save(self.values)
        fs.settings_path().write_text('{',encoding='utf8')
        with self.assertRaises(ValueError): fs.load()
    def test_unsupported_city_cannot_borrow_floor(self):
        fs.activate(self.values)
        for city in ('苏州',None,''):
            with self.assertRaises(ValueError): floor_value(dict(city=city,vehicle_name='经济5座',hours=4,kilometers=50))
    def test_ui_save_switch_reset_and_unsaved_guard(self):
        import tkinter as tk
        from tkinter import ttk
        from charter_quotes.floor_editor import build
        os.environ['TCL_LIBRARY'] = str(Path(__file__).parent/'recovered-v2.9/_tcl_data')
        os.environ['TK_LIBRARY'] = str(Path(__file__).parent/'recovered-v2.9/_tk_data')
        root = tk.Tk()
        root.withdraw()
        try:
            frame = ttk.Frame(root)
            controls=[]
            ready=build(frame,controls,Path(self.temp.name))
            state=frame.floor_editor_state
            self.assertEqual(len(state['tabs'].tabs()),2)
            self.assertTrue(ready())
            state['fields']['上海']['经济5座'][0].set('999')
            self.assertFalse(ready())
            state['tabs'].select(1)
            state['fields']['杭州']['经济5座'][0].set('777')
            state['save']('杭州')
            self.assertEqual(fs.load()['上海']['经济5座'][0],fs.DEFAULT_FLOORS['经济5座'][0])
            self.assertFalse(ready())
            state['save']('上海')
            self.assertTrue(ready())
            state['reset']('杭州')
            self.assertEqual(state['fields']['上海']['经济5座'][0].get(),'999')
            self.assertFalse(ready())
        finally: root.destroy()

if __name__=='__main__':
    (Path(__file__).parent/'test-data').mkdir(exist_ok=True)
    unittest.main(verbosity=2)
