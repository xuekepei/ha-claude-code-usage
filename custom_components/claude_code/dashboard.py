"""Claude Code 仪表盘：设置里有 claude-code 仪表盘就沿用它，没有就由集成自己提供一个。"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.components.lovelace.dashboard import LovelaceStorage
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DASHBOARD,
    DASHBOARD_ICON,
    DASHBOARD_STORAGE_ID,
    DASHBOARD_VERSION,
    DASHBOARD_VERSION_KEY,
    DATE_COLLECTION,
    DOMAIN,
    KINDS,
    LABELS,
    TITLE,
    TOTAL_NAME,
    TOTAL_SOURCE,
    UNITS,
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_register_panel(hass: HomeAssistant) -> bool:
    """设置里没有 claude-code 仪表盘时注册集成自己的，返回是否注册了。"""
    data = hass.data.get(LOVELACE_DATA)
    if data is None or DASHBOARD in data.dashboards:
        return False
    data.dashboards[DASHBOARD] = LovelaceStorage(hass, {
        "id": DASHBOARD_STORAGE_ID,
        "url_path": DASHBOARD,
        "title": TITLE,
        "icon": DASHBOARD_ICON,
        "show_in_sidebar": True,
        "require_admin": False,
        "mode": "storage",
    })
    frontend.async_register_built_in_panel(
        hass, "lovelace", sidebar_title=TITLE, sidebar_icon=DASHBOARD_ICON,
        frontend_url_path=DASHBOARD, config={"mode": "storage"},
    )
    return True


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, DASHBOARD)
    if data := hass.data.get(LOVELACE_DATA):
        data.dashboards.pop(DASHBOARD, None)


async def async_update(hass: HomeAssistant, names: dict[str, str]) -> None:
    """仪表盘还是旧版布局、或有电脑没出现在图表里时，重新生成；手改过的布局只在这两种情况下被覆盖。"""
    data = hass.data.get(LOVELACE_DATA)
    if data is None or (dashboard := data.dashboards.get(DASHBOARD)) is None:
        return
    # id 是哈希，按显示名排，图例顺序才有规律
    ids = sorted(names, key=lambda i: (names[i].lower(), i))
    try:
        current = await dashboard.async_load(False)
    except ConfigNotFound:
        current = None
    if (
        current
        and current.get(DASHBOARD_VERSION_KEY, 1) >= DASHBOARD_VERSION
        and all(f'"{i}"' in json.dumps(current) for i in ids)
    ):
        return
    try:
        await dashboard.async_save(_build(ids))
    except HomeAssistantError as err:
        _LOGGER.warning("Cannot update dashboard %s: %s", DASHBOARD, err)


def _build(ids: list[str]) -> dict[str, Any]:
    # 标题放在单独的 heading 里：图表自带标题时右上角会出现跳 HA 历史页的箭头，
    # 而外部统计不是实体，那个页面只会显示「未找到实体」
    def heading(kind: str) -> dict[str, Any]:
        _, unit, unit_cn = UNITS[kind]
        return {"type": "heading", "heading": f"{LABELS[kind]} · {unit}（{unit_cn}）", "heading_style": "subtitle"}

    def graph(kind: str, total: bool, **options: Any) -> dict[str, Any]:
        return {
            "type": "statistics-graph",
            "entities": (
                [f"{TOTAL_SOURCE}:{kind}"] if total else [i for i in ids if i.startswith(f"{DOMAIN}:{kind}_")]
            ),
            "stat_types": ["change"],
            "chart_type": "bar",
            "grid_options": {"columns": "full"},
            **options,
        }

    # 第一行是全部电脑的合计，第二行按电脑分开；左边按天，右边按周
    overview = [
        {
            "type": "grid",
            "cards": [{"type": "heading", "heading": f"{group} · {title}"}]
            + [c for k in KINDS for c in (heading(k), graph(k, total, period=period, days_to_show=days))],
        }
        for group, total in ((TOTAL_NAME, True), ("各电脑", False))
        for title, period, days in (("按天（近 30 天）", "day", 30), ("按周（近半年）", "week", 182))
    ]
    # 历史页：用日期选择器任意翻看某天 / 周 / 月 / 年，图表粒度随选择自动变（一天按小时，一年按月）
    # 每类上面是合计，下面按电脑分开
    selection = {"energy_date_selection": True, "collection_key": DATE_COLLECTION}
    history = [{
        "type": "grid",
        "column_span": 2,
        "cards": [
            {"type": "energy-date-selection", "collection_key": DATE_COLLECTION, "grid_options": {"columns": "full"}},
        ] + [
            {
                "type": "vertical-stack",
                "grid_options": {"columns": 12},
                "cards": [heading(k), graph(k, True, **selection), graph(k, False, **selection)],
            }
            for k in KINDS
        ],
    }]
    return {
        "title": TITLE,
        DASHBOARD_VERSION_KEY: DASHBOARD_VERSION,
        "views": [
            {"title": "概览", "path": "usage", "type": "sections", "max_columns": 2, "sections": overview},
            {"title": "历史", "path": "history", "type": "sections", "max_columns": 2, "sections": history},
        ],
    }
