"""Retain verified supplier validation and lazy grouping; make quote I/O async."""
import asyncio
import concurrent.futures
from ._legacy_async_probe import AsyncSuppliers, BatchProbe as LegacyBatchProbe
from .async_pipeline import AsyncQuotePipeline
from .web_provider import WebAccessStopped

class BatchProbe(LegacyBatchProbe):
    def __init__(self, saz, resources, stopped=lambda: False, progress=print):
        super().__init__(saz,resources,stopped,progress)
        self.pipeline = AsyncQuotePipeline(self.templates,stopped,progress)
        self.async_supplier = self.pipeline.supplier
        self.provider.fetch = self._fetch

    def _wait(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine,self.loop)
        try:
            while True:
                try:
                    return future.result(timeout=0.1)
                except concurrent.futures.TimeoutError:
                    if self.stopped():
                        future.cancel()
                        raise WebAccessStopped('已请求停止')
        except BaseException:
            future.cancel()
            raise

    def _fetch(self, query):
        # A group is loaded lazily, after reset completes. Never prefetch bookings.
        quotes, refs = self._wait(self.pipeline.fetch(query,self.provider.selected,fresh=True))
        self.provider.supplier_refs = refs
        self.provider.last_request = self.async_supplier.last_start
        return quotes

    def __exit__(self, *args):
        try:
            asyncio.run_coroutine_threadsafe(self.pipeline.close(),self.loop).result(timeout=30)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=30)
            if not self.thread.is_alive(): self.loop.close()
