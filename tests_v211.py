"""Offline parser, coroutine, cancellation, and desktop regression tests."""
import asyncio
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from module_runtime import ROOT, install
install()
from charter_quotes.async_pipeline import AsyncQuotePipeline, READ_OPERATIONS
from charter_quotes.core import Query
from charter_quotes.query_time import market_query_date
from charter_quotes.saz_provider import SazProvider
from charter_quotes.web_provider import WebAccessStopped, CITIES as CITY_IDS

PACKAGES=[(4,50),(4,100),(8,100),(8,200),(10,300)]

def fixture(name,payload):
    # Deliberately synthetic test data, never an assertion about live prices.
    if name=='EstimatePriceByLineGraphic':
        return dict(resstatus=dict(rcode=200),lines=[dict(mode='agg',priceMark='initial')],pt='synthetic-test')
    condition=copy.deepcopy(payload['searchCondition'])
    condition['dptCname']=next(c for c,i in CITY_IDS.items() if str(i)==str(condition['dptCid']))
    mark=payload['productRef']['priceMark']
    selected=mark if mark.startswith('p@') else 'p@4|50'
    return dict(resstatus=dict(rcode=200),searchCondition=condition,pt='synthetic-test',
                lineProperties=[dict(aggLines=[dict(isDefaultSelected=f'p@{h}|{km}'==selected,
                    linePriceMark=f'p@{h}|{km}',properties=[dict(propertyCode='package',propertyValueId=f'p@{h}|{km}')]) for h,km in PACKAGES])],
                lineInfo=dict(lineId=999),vehicle=dict(list=[dict(grpid='test5',amtshow=500,priceMark='synthetic-car')],
                grps={'test5':dict(vehicleSeat=5,seat=4,nm='经济5座')}))

class AsyncQueries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls=[]
        self.active=self.maximum=0
        self.failure=False
        self.server=await asyncio.start_server(self.handle,'127.0.0.1',0)
        port=self.server.sockets[0].getsockname()[1]
        self.templates={name:dict(url=f'http://127.0.0.1:{port}/{name}',headers={'Content-Type':'application/json'},payload={}) for name in READ_OPERATIONS}
        self.pipeline=AsyncQuotePipeline(self.templates,progress=lambda *_:None,interval=0)
        self.date=market_query_date()
    async def asyncTearDown(self):
        await self.pipeline.close()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(.08)
    async def handle(self,reader,writer):
        try:
            headers=(await reader.readuntil(b'\r\n\r\n')).decode('ascii')
            length=int(next(line.split(':',1)[1] for line in headers.splitlines() if line.lower().startswith('content-length:')))
            payload=json.loads(await reader.readexactly(length))
            name=headers.split()[1].split('/')[-1]
            self.calls.append((name,payload,time.monotonic()))
            self.active+=1;self.maximum=max(self.maximum,self.active)
            await asyncio.sleep(.06)
            self.active-=1
            if self.failure:
                body=b'{}';status='430 Rejected'
            else:
                body=json.dumps(fixture(name,payload)).encode('utf8');status='200 OK'
            writer.write(f'HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
            await writer.drain()
        except (asyncio.IncompleteReadError,ConnectionError):pass
        finally:
            writer.close()
            await writer.wait_closed()
    def query(self,city='上海',h=4,km=50):return Query(city,self.date,h,km,1,'total_including_driver',9)
    async def test_real_parser_matches_previous_parser(self):
        old=SazProvider(self.templates,__import__('threading').Event(),lambda *_:None,{'_with_suppliers':False})
        old.post=fixture
        expected=old.fetch(self.query())
        quotes,refs=await self.pipeline.fetch(self.query())
        self.assertEqual(quotes,expected)
        self.assertEqual(refs,old.supplier_refs)
    async def test_parallel_packages_deduplicate_and_preserve_order(self):
        results=await self.pipeline.fetch_many([self.query(),self.query('杭州',8,100),self.query()])
        self.assertEqual([q[0][0].city for q in results],['上海','杭州','上海'])
        self.assertEqual(results[0],results[2])
        self.assertEqual(sum(name=='EstimatePriceByLineGraphic' for name,*_ in self.calls),2)
        self.assertGreaterEqual(self.maximum,2)
        self.assertLessEqual(self.maximum,2)
        self.assertIs(self.pipeline.transport.session,self.pipeline.supplier.session)
    async def test_http_failure_stops_without_retry(self):
        self.failure=True
        with self.assertRaises(WebAccessStopped):await self.pipeline.fetch(self.query())
        self.assertEqual(len(self.calls),1)
    async def test_read_path_cannot_create_booking(self):
        with self.assertRaises(WebAccessStopped):await self.pipeline.read('SaveBookingInfo',{})
        self.assertEqual(self.calls,[])
    async def test_global_interval_and_concurrency(self):
        self.pipeline.transport.interval=.025
        await self.pipeline.fetch_many([self.query(),self.query('杭州')])
        gaps=[b[2]-a[2] for a,b in zip(self.calls,self.calls[1:])]
        self.assertTrue(all(g>.017 for g in gaps),gaps)
        self.assertLessEqual(self.maximum,2)
    async def test_cancel_closes_all_pending_requests(self):
        task=asyncio.create_task(self.pipeline.fetch_many([self.query(),self.query('杭州')]))
        await asyncio.sleep(.015)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.pipeline._pending,{})
        await self.pipeline.close()
        self.assertTrue(self.pipeline.transport.session.closed)
    async def test_unknown_supplier_failure_does_not_stop_other_city_quotes(self):
        self.pipeline.supplier.failed=True
        quotes,_=await self.pipeline.fetch(self.query('杭州'))
        self.assertEqual(quotes[0].city,'杭州')
    async def test_fresh_details_after_explicit_invalidation(self):
        await self.pipeline.fetch(self.query())
        first=len(self.calls)
        self.pipeline.invalidate_prices()
        await self.pipeline.fetch(self.query())
        self.assertEqual(len(self.calls),first+1)
        self.assertEqual(sum(n=='EstimatePriceByLineGraphic' for n,*_ in self.calls),1)
    async def test_date_rollover_aborts(self):
        with patch('charter_quotes.async_pipeline.market_query_date',return_value='2099-01-01'):
            with self.assertRaises(WebAccessStopped):await self.pipeline.fetch(self.query())
        self.assertEqual(self.calls,[])
    async def test_next_package_does_not_refetch_city_or_initial_detail(self):
        await self.pipeline.fetch(self.query())
        first=len(self.calls)
        await self.pipeline.fetch(self.query(h=8,km=100),fresh=True)
        self.assertEqual(len(self.calls),first+1)
        await self.pipeline.fetch(self.query(h=8,km=100),fresh=True)
        self.assertEqual(len(self.calls),first+2)
    async def test_worker_bridge_uses_coroutine_transport_and_closes(self):
        from charter_quotes.async_probe import BatchProbe
        from charter_quotes.floor_settings import activate, defaults
        from hourly_reprice import resources_today
        activate(defaults())
        item=next(r for r in resources_today(['经济5座'],['杭州']) if r['hours']==4 and r['kilometers']==50)
        def work():
            with patch('charter_quotes._legacy_async_probe.load_saz',return_value=self.templates):
                with BatchProbe('synthetic.saz',[item],progress=lambda *_:None) as probe:
                    probe.pipeline.transport.interval=0
                    result=probe(item)
                return result,probe
        result,probe=await asyncio.to_thread(work)
        self.assertEqual(result['city'],'杭州')
        self.assertEqual(result['target_price'],414)
        self.assertFalse(probe.thread.is_alive())
        self.assertTrue(probe.loop.is_closed())

class Desktop(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'test-data')
        self.env=patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name,'TCL_LIBRARY':str(ROOT/'recovered-v2.9/_tcl_data'),'TK_LIBRARY':str(ROOT/'recovered-v2.9/_tk_data')})
        self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def context(self):
        local=Path(self.temp.name)/'XiaMoChuQiuCharter';local.mkdir(exist_ok=True)
        return dict(VERSION='2.11',LOCAL=local,SESSION=local/'portable-query.saz',STOP=local/'portable-reprice.stop',LOG=local/'portable-reprice.log',__file__=str(ROOT/'portable_reprice.py'))
    def test_log_incremental_utf8_and_truncation(self):
        from charter_quotes.ui_shell import LogTail
        path=Path(self.temp.name)/'log.txt'
        path.write_bytes('上海成功'.encode())
        tail=LogTail(path)
        chunks=[]
        while tail.offset<path.stat().st_size:chunks.append(tail.read(2))
        self.assertEqual(''.join(chunks),'上海成功')
        self.assertEqual(tail.read(),'')
        path.write_text('新',encoding='utf8')
        self.assertEqual(tail.read(),'新')
    def test_ui_navigation_city_floor_lock_and_safe_close(self):
        from charter_quotes.ui_shell import Application
        g=self.context()
        app=Application(g)
        try:
            app.root.withdraw()
            app.root.update()
            for name in app.pages:app.select_page(name)
            app.select_city('杭州')
            self.assertEqual(app.selected_label.get(),'杭州')
            self.assertTrue(app.floors_ready())
            app.pages['城市底价'].floor_editor_state['fields']['上海']['经济5座'][0].set('666')
            self.assertFalse(app.floors_ready())
            g['SESSION'].write_bytes(b'test placeholder only')
            with patch('charter_quotes.ui_shell.messagebox.showinfo'):
                app.start('once')
                self.assertIsNone(app.proc)
            self.assertEqual(app.book.select(),str(app.pages['城市底价']))
            app.append_log('本地测试成功\n异常测试\n')
            self.assertIn('本地测试成功',app.text.get('1.0','end'))
        finally:app.root.destroy()
    def test_window_exit_guard_keeps_night_recovery(self):
        from charter_quotes.ui_shell import Application
        app=Application(self.context());app.root.withdraw()
        try:
            with patch.object(next(iter(app.night_cycles.values())),'state',return_value={'phase':'restoring'}),patch('charter_quotes.ui_shell.messagebox.showinfo') as info:
                app.close();info.assert_called_once();self.assertTrue(app.root.winfo_exists())
        finally:app.root.destroy()
    def test_task_city_routing_lock_and_stop_request(self):
        from charter_quotes.ui_shell import Application
        from unittest.mock import Mock
        g=self.context();g['SESSION'].write_bytes(b'synthetic placeholder')
        app=Application(g);app.root.withdraw()
        try:
            app.select_city('杭州')
            proc=Mock();proc.poll.return_value=None
            with patch('charter_quotes.ui_shell.subprocess.Popen',return_value=proc) as popen:
                app.start('apply')
            argv=popen.call_args.args[0]
            self.assertEqual(argv[-4:],['--job','apply','--city','杭州'])
            self.assertTrue(all(str(b.cget('state'))=='disabled' for b in app.buttons))
            app.stop()
            self.assertTrue(g['STOP'].exists())
            self.assertFalse(any(v.get() for v in app.night_enabled.values()))
            proc.poll.return_value=0;proc.returncode=0
            app.poll()
            self.assertIsNone(app.proc)
            self.assertTrue(all(str(b.cget('state'))=='normal' for b in app.buttons))
        finally:
            if app._poll_id is not None:app.root.after_cancel(app._poll_id)
            if app.stream:app.stream.close()
            app.root.destroy()

if __name__=='__main__':unittest.main(verbosity=2)
