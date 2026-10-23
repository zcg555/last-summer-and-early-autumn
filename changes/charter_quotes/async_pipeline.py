"""Coroutine HTTP transport with the original, unchanged quote parser.

The parser runs locally against recorded responses. When it needs a response,
it yields a private signal; the event loop awaits HTTP and resumes parsing.
Only the two read-only quote operations may use this replay adapter.
"""
import asyncio
import copy
import json
import threading
import time
from dataclasses import asdict
from datetime import datetime
import aiohttp
from ._legacy_async_probe import AsyncSuppliers
from .saz_provider import SazProvider, load_saz
from .core import Query, SHANGHAI
from .quote_fields import PACKAGES
from .query_time import market_query_date
from .auto_reprice import plan_today
from .web_provider import WebAccessStopped, CITIES as CITY_IDS

READ_OPERATIONS = frozenset(('EstimatePriceByLineGraphic', 'QueryAggregateLineDetail'))

class _NeedResponse(BaseException):
    def __init__(self, name, payload):
        self.name, self.payload = name, copy.deepcopy(payload)

class SessionTransport(AsyncSuppliers):
    def __init__(self, templates, stopped, interval, gate=None):
        self.gate = gate if gate is not None else {'last_start': 0.0}
        previous_start = self.gate['last_start']
        super().__init__(templates,stopped,interval=interval,concurrency=2)
        self.gate['last_start'] = previous_start

    @property
    def last_start(self): return self.gate['last_start']

    @last_start.setter
    def last_start(self,value): self.gate['last_start'] = value

class ReplayParser(SazProvider):
    def __init__(self, templates, selected, use_time, stopped):
        super().__init__(templates, threading.Event(), lambda *_: None,
                         {'_with_suppliers': False, '_selected_vehicles': selected,
                          'web': {'departure_time': use_time}})
        self.replies = {}
        self.stopped_callback = stopped

    @staticmethod
    def request_key(name, payload):
        return name, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def post(self, name, payload):
        if self.stopped_callback():
            raise WebAccessStopped('已请求停止')
        if name not in READ_OPERATIONS:
            raise WebAccessStopped('报价解析阶段出现非只读请求，已停止')
        key = self.request_key(name, payload)
        if key not in self.replies:
            raise _NeedResponse(name, payload)
        return copy.deepcopy(self.replies[key])

class AsyncQuotePipeline:
    def __init__(self, templates, stopped=lambda: False, progress=print, interval=1.0):
        self.templates, self.stopped, self.progress = templates, stopped, progress
        self.transport = SessionTransport(templates,stopped,interval)
        self.supplier = SessionTransport(templates,stopped,interval,self.transport.gate)
        self.supplier.semaphore = self.transport.semaphore
        self.supplier.rate_lock = self.transport.rate_lock
        self._pending, self._responses = {}, {}
        self._city_cache = {}
        self._closed = False

    async def ensure_session(self):
        if self._closed:
            raise WebAccessStopped('查询会话已关闭')
        if self.transport.session is None:
            self.transport.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25), trust_env=True,
                connector=aiohttp.TCPConnector(limit=2),
                cookie_jar=aiohttp.CookieJar())
            self.supplier.session = self.transport.session

    def invalidate_prices(self):
        self._responses = {k:v for k,v in self._responses.items() if k[0] != 'QueryAggregateLineDetail'}
        for _,cache in self._city_cache.values():cache['details'].clear()

    async def read(self, name, payload):
        if name not in READ_OPERATIONS:
            raise WebAccessStopped('不允许在报价队列中创建预订记录')
        self.transport.check()
        key = ReplayParser.request_key(name, payload)
        cached = self._responses.get(key)
        if cached is not None and time.monotonic() - cached[0] < 120:
            return copy.deepcopy(cached[1])
        task = self._pending.get(key)
        if task is None:
            async def request():
                await self.ensure_session()
                result = await self.transport.post(name, payload)
                self._responses[key] = (time.monotonic(), copy.deepcopy(result))
                return result
            task = asyncio.create_task(request())
            self._pending[key] = task
        try:
            result = await asyncio.shield(task)
            self.transport.check()
            return copy.deepcopy(result)
        finally:
            if task.done() and self._pending.get(key) is task:
                self._pending.pop(key, None)

    async def fetch(self, query, selected=None, use_time='00:00', fresh=False):
        self.transport.check()
        if query.use_date != market_query_date():
            raise WebAccessStopped('已跨天，停止使用旧日期报价')
        self.progress(f'{query.city} {query.hours}小时/{query.kilometers}公里：协程读取报价')
        parser = ReplayParser(self.templates, selected, use_time, self.stopped)
        city_key=(query.city,query.use_date,use_time)
        cached=self._city_cache.get(city_key)
        seed_time=time.monotonic()
        if cached is not None and seed_time-cached[0]<120:
            seed_time=cached[0]
            seed=copy.deepcopy(cached[1])
            package=f'p@{query.hours}|{query.kilometers}'
            if fresh:
                seed['details'].pop(package,None)
                mark=seed['marks'].get(package)
                for key in list(self._responses):
                    if key[0]=='QueryAggregateLineDetail':
                        data=json.loads(key[1])
                        condition=data.get('searchCondition',{})
                        if data.get('productRef',{}).get('priceMark')==mark and condition.get('dptDate')==query.use_date and str(condition.get('dptCid'))==str(CITY_IDS[query.city]):
                            self._responses.pop(key,None)
            parser.cache[(query.city,query.use_date)]=seed
        initial_cache = copy.deepcopy(parser.cache)
        for _ in range(32):
            self.transport.check()
            parser.cache = copy.deepcopy(initial_cache)
            parser.supplier_refs.clear()
            try:
                quotes = parser.fetch(query)
            except _NeedResponse as need:
                result = await self.read(need.name, need.payload)
                parser.replies[parser.request_key(need.name, need.payload)] = result
                continue
            if query.use_date != market_query_date():
                raise WebAccessStopped('已跨天，停止使用旧日期报价')
            self._city_cache[city_key]=(seed_time,copy.deepcopy(parser.cache[(query.city,query.use_date)]))
            return quotes, copy.deepcopy(parser.supplier_refs)
        raise WebAccessStopped('报价请求依赖异常，已停止')

    async def fetch_many(self, queries, selected=None, use_time='00:00'):
        # Exactly two workers. Results remain in the caller's city/package order.
        queue = asyncio.Queue()
        for i, query in enumerate(queries): queue.put_nowait((i, query))
        results = [None] * len(queries)
        async def worker():
            while not queue.empty():
                index, query = queue.get_nowait()
                results[index] = await self.fetch(query, selected, use_time)
        workers = [asyncio.create_task(worker()) for _ in range(min(2,len(queries)))]
        try:
            await asyncio.gather(*workers)
            return results
        except BaseException:
            for task in workers: task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await self.cancel_pending()
            raise

    async def cancel_pending(self):
        pending = list(self._pending.values())
        self._pending.clear()
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)

    async def close(self):
        await self.cancel_pending()
        await self.transport.close()
        self._closed = True

async def collect_async(saz, vehicles, use_time='00:00', cities=('上海','杭州'), stopped=lambda: False):
    today = market_query_date()
    queries = [Query(city,today,h,km,1,'total_including_driver',9)
               for city in cities for h,km in PACKAGES if not (city=='杭州' and (h,km)==(4,100))]
    pipeline = AsyncQuotePipeline(load_saz(saz),stopped)
    try:
        results = await pipeline.fetch_many(queries,vehicles,use_time)
        rows = [dict(asdict(q),collected_at=datetime.now(SHANGHAI).isoformat())
                for quotes, _ in results for q in quotes]
        if not rows: raise RuntimeError('次日没有有效报价，未修改任何价格')
        return plan_today(rows,use_date=today)
    finally:
        await pipeline.close()
