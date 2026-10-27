"""添加集成时生成 webhook 地址；「重新配置」里可以再看地址或换一个。"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError

from .const import DOMAIN, TITLE


def _placeholders(hass: HomeAssistant, webhook_id: str) -> dict[str, str]:
    try:
        # 内网地址给别的电脑用不了，宁可只给路径
        url = webhook.async_generate_url(hass, webhook_id, allow_internal=False)
    except NoURLAvailableError:
        # 没配外部地址时只给路径，前面自己补上从外面访问 HA 的地址
        url = webhook.async_generate_path(webhook_id)
    return {"webhook_url": url}


class ClaudeCodeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user")
        webhook_id = webhook.async_generate_id()
        return self.async_create_entry(
            title=TITLE,
            data={CONF_WEBHOOK_ID: webhook_id},
            description_placeholders=_placeholders(self.hass, webhook_id),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        webhook_id = entry.data[CONF_WEBHOOK_ID]
        if user_input is None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema({vol.Required("regenerate", default=False): bool}),
                description_placeholders=_placeholders(self.hass, webhook_id),
            )
        if user_input["regenerate"]:
            webhook_id = webhook.async_generate_id()
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_WEBHOOK_ID: webhook_id})
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_abort(
            reason="reconfigure_successful", description_placeholders=_placeholders(self.hass, webhook_id)
        )
