"""Claude Code 用量：各电脑通过 webhook 推送按小时的 token 数，这里导入长期统计、算全部电脑的合计、维护仪表盘。

webhook 只接受 usage.PAYLOAD 定义的格式，只会写 claude_code / claude_code_total 两个来源的统计，
所以地址泄漏的后果仅限于被写入假用量；需要时在集成的「重新配置」里换一个地址。
"""

from __future__ import annotations

from http import HTTPStatus
import logging

from aiohttp import web
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.components.http import KEY_HASS, HomeAssistantView, require_admin
from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import dashboard, usage
from .const import DASHBOARD_STORAGE_ID, DOMAIN, TITLE

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type ClaudeCodeConfigEntry = ConfigEntry[usage.Runtime]


class WebhookPathView(HomeAssistantView):
    """v4 及以前的推送脚本拿 HA 令牌直连；升级后用令牌来这里换 webhook 路径，换到就删掉本地令牌。"""

    url = "/api/claude_code/webhook"
    name = "api:claude_code:webhook"

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
            return self.json_message("Claude Code Usage 集成还没添加", HTTPStatus.NOT_FOUND)
        return self.json({"webhook_path": webhook.async_generate_path(entries[0].data[CONF_WEBHOOK_ID])})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.http.register_view(WebhookPathView())
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ClaudeCodeConfigEntry) -> bool:
    store: Store[dict] = Store(hass, 1, DOMAIN)
    runtime = usage.Runtime(store, await store.async_load() or {})
    entry.runtime_data = runtime

    async def handle(hass: HomeAssistant, webhook_id: str, request: web.Request) -> web.Response:
        try:
            payload = usage.PAYLOAD(await request.json())
        except (ValueError, vol.Invalid) as err:
            return web.json_response({"error": str(err)}, status=400)
        # webhook 组件吞掉异常后照样回 200，这里自己回 500，推送脚本才知道失败了
        try:
            async with runtime.lock:
                return web.json_response(await usage.async_push(hass, runtime, payload))
        except Exception as err:
            _LOGGER.exception("Failed to import usage from %s", payload["device"])
            return web.json_response({"error": repr(err)}, status=500)

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    webhook.async_register(hass, DOMAIN, TITLE, webhook_id, handle, local_only=False, allowed_methods=["POST"])
    # 重新配置换地址后 entry.data 里已经是新 id，卸载时要注销的是这里注册的旧 id
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
    if dashboard.async_register_panel(hass):
        entry.async_on_unload(lambda: dashboard.async_remove_panel(hass))

    async def refresh() -> None:
        # 刚装好时就把仪表盘建好，不用等第一次推送
        await get_instance(hass).async_db_ready
        async with runtime.lock:
            await usage.async_refresh_dashboard(hass, runtime)

    entry.async_create_background_task(hass, refresh(), f"{DOMAIN} dashboard")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClaudeCodeConfigEntry) -> bool:
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # 删除集成时只清掉它自己的记录和仪表盘配置，长期统计保留
    await Store(hass, 1, DOMAIN).async_remove()
    await Store(hass, 1, f"lovelace.{DASHBOARD_STORAGE_ID}").async_remove()
