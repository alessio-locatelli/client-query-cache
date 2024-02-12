from typing import Any

import motor.motor_asyncio


class CachedAsyncIOMotorClient(motor.motor_asyncio.AsyncIOMotorClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
