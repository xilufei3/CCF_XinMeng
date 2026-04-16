import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ThreadLockManager:
    def __init__(self) -> None:
        self._registry_lock = asyncio.Lock()
        self._thread_locks: dict[str, asyncio.Lock] = {}

    async def _get_lock(self, thread_id: str) -> asyncio.Lock:
        async with self._registry_lock:
            if thread_id not in self._thread_locks:
                self._thread_locks[thread_id] = asyncio.Lock()
            return self._thread_locks[thread_id]

    @asynccontextmanager
    async def lock(self, thread_id: str) -> AsyncIterator[None]:
        lock = await self._get_lock(thread_id)
        async with lock:
            yield


thread_lock_manager = ThreadLockManager()
