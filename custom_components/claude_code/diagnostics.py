"""诊断信息：各电脑最近一次推送的时间和脚本版本。webhook 地址不放进来，诊断文件常被拿去分享。"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import ClaudeCodeConfigEntry


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ClaudeCodeConfigEntry) -> dict[str, Any]:
    data = entry.runtime_data.data
    return {"devices": data.get("devices", {}), "retired": data.get("retired", [])}
