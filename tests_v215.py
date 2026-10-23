"""Offline browser regression: all browser requests are intercepted synthetic fixtures."""
import html
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from module_runtime import ROOT, install
install()
from charter_quotes.vbk_query import VbkReadError, validate_resource
from charter_quotes.release_info import version_key, register_release, newer_release
from hourly_reprice import VbkEditor, LIST_URL, error_reason

ITEM=dict(resource_id='2049846',city='杭州',vehicle_name='丰田埃尔法',hours=8,kilometers=100,line_id='2738')
CELLS=['',ITEM['resource_id'],'','','杭州','','2738','','8小时/100公里','','丰田埃尔法','','','上线']
HEADERS=['选择','资源ID','资源名','分类','城市','其他','线路ID','其他2','套餐','其他3','车型','其他4','其他5','状态']

def fixture(mode):
    cells=list(CELLS)
    headers=list(HEADERS)
    if mode=='mismatch':cells[10]='经济5座'
    if mode=='reordered':
        headers=['状态','车型','套餐','线路ID','城市','资源ID']
        cells=['上线','丰田埃尔法','8小时 / 100公里','2738','杭州','2049846']
    script='''
        const cells=CELLS,heads=HEADS,mode=MODE;
        const render=values=>'<tr data-row-key="2049846">'+values.map(v=>'<td>'+v+'</td>').join('')+'</tr>';
        const body=document.querySelector('tbody');
        document.querySelector('#query').onclick=async()=>{
            window.queryCount++;
            const request=fetch('/synthetic-resource-query?resource_id='+document.querySelector('input').value);
            if(mode==='stale') { await request; return; }
            if(mode==='busy') document.querySelector('.ant-spin-spinning').style.display='block';
            body.innerHTML=render(['partial']);
            await request;
            setTimeout(()=>{
                body.innerHTML=mode==='empty'?'':render(cells)+(mode==='duplicate'?render(cells):'');
                document.querySelector('thead').innerHTML='<tr>'+heads.map(v=>'<th>'+v+'</th>').join('')+'</tr>';
                if(mode==='busy') setTimeout(()=>document.querySelector('.ant-spin-spinning').style.display='none',450);
            },mode==='slow'?550:80);
        };
        window.queryCount=0;
    '''.replace('CELLS',json.dumps(cells,ensure_ascii=False)).replace('HEADS',json.dumps(headers,ensure_ascii=False)).replace('MODE',json.dumps(mode))
    initial=list(CELLS);initial[13]='下线'
    row='<tr data-row-key="2049846">'+''.join('<td>'+html.escape(c)+'</td>' for c in initial)+'</tr>'
    return '<html><body><button>重 置</button><label>资源ID<input aria-label="资源ID"></label><button id="query">查 询</button><div class="ant-spin-spinning" style="display:none">加载中</div><div class="ant-table"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in HEADERS)+'</tr></thead><tbody>'+row+'</tbody></table></div><script>'+script+'</script></body></html>'

class BrowserReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'recovered-v2.9/browsers')
        cls.pw=sync_playwright().start()
        cls.browser=cls.pw.chromium.launch(headless=True,executable_path=cls.pw.chromium.executable_path)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def check(self,mode,timeout=1800):
        page=self.browser.new_page()
        calls=[]
        def route(request_route):
            request=request_route.request
            calls.append(request.url)
            if request.url==LIST_URL:
                request_route.fulfill(status=200,content_type='text/html; charset=utf-8',body=fixture(mode))
            elif '/synthetic-resource-query?' in request.url:
                request_route.fulfill(status=430 if mode=='http_error' else 200,content_type='application/json',body='{"synthetic":true}')
            else:request_route.abort()
        page.route('**/*',route)
        editor=VbkEditor(page,[])
        editor.query_timeout_ms=timeout
        return page,editor,calls
    def test_delayed_partial_cells_do_not_raise_index_error(self):
        page,editor,calls=self.check('slow')
        try:
            self.assertTrue(editor.verify_resource(ITEM))
            self.assertEqual(page.evaluate('window.queryCount'),1)
            self.assertEqual(len(calls),2)
            self.assertNotIn('priceInfo',calls[0])
        finally:page.close()
    def test_reordered_columns_use_header_names(self):
        page,editor,_=self.check('reordered')
        try:self.assertTrue(editor.verify_resource(ITEM))
        finally:page.close()
    def test_loading_overlay_must_end(self):
        page,editor,_=self.check('busy')
        try:
            self.assertTrue(editor.verify_resource(ITEM))
            self.assertFalse(page.locator('.ant-spin-spinning').is_visible())
        finally:page.close()
    def test_unchanged_old_row_is_not_accepted(self):
        page,editor,_=self.check('stale',900)
        try:
            with self.assertRaisesRegex(VbkReadError,'尚未刷新'):editor.verify_resource(ITEM)
        finally:page.close()
    def test_empty_result_reports_timeout_not_index_error(self):
        page,editor,_=self.check('empty',900)
        try:
            with self.assertRaisesRegex(VbkReadError,'未返回目标资源行'):editor.verify_resource(ITEM)
        finally:page.close()
    def test_duplicate_resource_rows_fail_closed(self):
        page,editor,_=self.check('duplicate',900)
        try:
            with self.assertRaisesRegex(VbkReadError,'不唯一'):editor.verify_resource(ITEM)
        finally:page.close()
    def test_identity_mismatch_is_explicit(self):
        page,editor,_=self.check('mismatch',1000)
        try:
            with self.assertRaisesRegex(VbkReadError,'vehicle_name'):editor.verify_resource(ITEM)
        finally:page.close()
    def test_http_rejection_never_uses_old_table(self):
        page,editor,_=self.check('http_error',900)
        try:
            with self.assertRaisesRegex(VbkReadError,'430'):editor.verify_resource(ITEM)
        finally:page.close()
    def test_merchant_cells_wait_for_full_row(self):
        from charter_quotes.vbk_query import wait_merchant_cells
        page=self.browser.new_page()
        try:
            page.set_content('<table><tbody><tr><td>1572124 - 夏末初秋国际旅行社(上海)有限公司</td></tr></tbody></table>')
            page.evaluate('''()=>setTimeout(()=>{document.querySelector('tr').innerHTML='<td>套餐</td><td>1572124 - 夏末初秋国际旅行社(上海)有限公司</td>'+Array.from({length:9},(_,i)=>'<td>'+i+'</td>').join('')},200)''')
            result=wait_merchant_cells(page,1500)
            self.assertEqual(len(result),11)
        finally:page.close()

class ReleaseAndValidationTests(unittest.TestCase):
    def test_numeric_version_order(self):self.assertGreater(version_key('2.15'),version_key('2.9'))
    def test_release_catalog_never_downgrades(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'test-data') as td:
            folder=Path(td);exe=folder/'synthetic.exe';exe.write_bytes(b'synthetic test placeholder')
            catalog=folder/'latest.json'
            self.assertTrue(register_release('2.15',exe,catalog))
            self.assertFalse(register_release('2.14',exe,catalog))
            self.assertEqual(newer_release('2.14',catalog)['version'],'2.15')
            self.assertIsNone(newer_release('2.15',catalog))
            exe.unlink();self.assertIsNone(newer_release('2.14',catalog))
    def test_column_bounds_and_offline_status(self):
        with self.assertRaises(VbkReadError):validate_resource(dict(cells=['2049846'],headers=[]),ITEM)
        offline=list(CELLS);offline[13]='下线'
        self.assertFalse(validate_resource(dict(cells=offline,headers=HEADERS),ITEM))
    def test_backend_errors_are_not_reported_as_quote_validation(self):
        self.assertIn('后台表格',error_reason(IndexError('synthetic')))
        target=type('TargetClosedError',(Exception,),{})
        self.assertIn('VBK',error_reason(target()))

if __name__=='__main__':unittest.main(verbosity=2)
