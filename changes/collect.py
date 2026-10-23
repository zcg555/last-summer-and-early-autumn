def collect(saz, vehicles, use_time='00:00', cities=('上海','杭州')):
    import asyncio
    from charter_quotes.async_pipeline import collect_async
    return asyncio.run(collect_async(saz, vehicles, use_time, cities, stopped=lambda: (LOCAL/'portable-reprice.stop').exists()))
