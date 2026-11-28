import asyncio


async def join_cleanup[T](task: asyncio.Task[T]) -> T:
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled and task.exception() is None:
        raise asyncio.CancelledError
    return task.result()
