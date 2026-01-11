from __future__ import annotations

from diskcache import Cache
from onepace.core.config import config

cache = Cache(str(config.CACHE_PATH))
