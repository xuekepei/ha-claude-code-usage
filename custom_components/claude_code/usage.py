"""接收各电脑推送的按小时用量：导入长期统计、重算全部电脑的合计。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_list_statistic_ids,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import dashboard
from .const import DATA_VERSION, DOMAIN, EPOCH, HOUR, KINDS, LABELS, MAX_HOURS, TOTAL_NAME, TOTAL_SOURCE, UNITS

_LOGGER = logging.getLogger(__name__)


@dataclass
class Runtime:
    """集成运行时的状态。

    data 存在 .storage/claude_code：
    devices 记每台电脑的显示名和最近一次全量推送时的 DATA_VERSION；
    retired 是换过 id 的旧设备，不再算进合计和仪表盘。
    """

    store: Store[dict[str, Any]]
    data: dict[str, Any]
    # 一次只处理一个推送：合计要读其他电脑已经写进数据库的值
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _hour(value: Any) -> datetime:
    t = dt_util.parse_datetime(str(value))
    if t is None or t.tzinfo is None or t.minute or t.second or t.microsecond:
        raise vol.Invalid(f"不是带时区的整点时间：{value}")
    return dt_util.as_utc(t)


def _check(payload: dict[str, Any]) -> dict[str, Any]:
    start, end = payload["start"], payload["end"]
    if not start <= end <= start + MAX_HOURS * HOUR:
        raise vol.Invalid("start / end 不对")
    hours = {}
    for key, counts in payload["hours"].items():
        t = _hour(key)
        if not start <= t <= end:
            raise vol.Invalid(f"{key} 不在 start 和 end 之间")
        hours[t] = counts
    payload["hours"] = hours
    return payload


_DEVICE = vol.All(str, vol.Length(max=64), vol.Match(r"^[a-z0-9]+(_[a-z0-9]+)*$"))
_COUNTS = vol.All([vol.All(int, vol.Range(min=0))], vol.Length(min=len(KINDS), max=len(KINDS)))

# 推送格式：hours 里只放有用量的小时，start 到 end（含）之间没列出的小时算 0；
# base 是 start 之前的累计 token 数，各类型的顺序同 KINDS
PAYLOAD = vol.All(
    vol.Schema(
        {
            vol.Required("device"): _DEVICE,
            vol.Required("name"): vol.All(str, vol.Strip, vol.Length(min=1, max=64)),
            vol.Required("start"): _hour,
            vol.Required("end"): _hour,
            vol.Required("base"): _COUNTS,
            vol.Required("hours"): {str: _COUNTS},
            vol.Optional("full", default=False): bool,
            # 设备 id 变了时带上旧 id，旧统计会被删掉
            vol.Optional("replaces"): _DEVICE,
            vol.Optional("version"): int,
        },
        extra=vol.REMOVE_EXTRA,
    ),
    _check,
)


def _statistic_ids(device: str) -> list[str]:
    return [f"{DOMAIN}:{kind}_{device}" for kind in KINDS]


def _import(hass: HomeAssistant, statistic_id: str, name: str, kind: str, sums) -> None:
    async_add_external_statistics(
        hass,
        {
            "statistic_id": statistic_id,
            "source": statistic_id.split(":", 1)[0],
            "name": name,
            "unit_of_measurement": UNITS[kind][1],
            "unit_class": None,
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
        },
        [{"start": t, "sum": round(s, 6)} for t, s in sums],
    )


async def async_push(hass: HomeAssistant, runtime: Runtime, payload: dict[str, Any]) -> dict[str, Any]:
    device, name = payload["device"], payload["name"]
    instance = get_instance(hass)

    # 没有用量的小时也要写一行，覆盖掉之前可能推过的旧值
    rows = []
    running = list(payload["base"])
    t = payload["start"]
    while t <= payload["end"]:
        if values := payload["hours"].get(t):
            running = [a + b for a, b in zip(running, values, strict=True)]
        rows.append((t, running))
        t += HOUR
    for i, (kind, statistic_id) in enumerate(zip(KINDS, _statistic_ids(device), strict=True)):
        _import(hass, statistic_id, f"{name} {LABELS[kind]}", kind, [(t, s[i] / UNITS[kind][0]) for t, s in rows])
    # 导入是排队执行的，等写进数据库再算合计
    await instance.async_block_till_done()

    devices = runtime.data.setdefault("devices", {})
    retired = runtime.data.setdefault("retired", [])
    data_version = DATA_VERSION if payload["full"] else devices.get(device, {}).get("data_version")
    devices[device] = {
        "name": name,
        "data_version": data_version,
        # 在诊断信息里看各电脑还在不在推、脚本是哪个版本
        "last_push": dt_util.utcnow().isoformat(),
        "client_version": payload.get("version"),
    }
    if device in retired:
        retired.remove(device)
    result: dict[str, Any] = {"imported": len(rows), "full_needed": data_version != DATA_VERSION}

    old = payload.get("replaces")
    if old and old != device and old not in retired:
        retired.append(old)
        devices.pop(old, None)
        if await _async_clear_if_covered(hass, old, rows[-1][1]):
            result["cleared"] = old
        else:
            result["message"] = f"旧设备 {old} 的累计比这次推送的多（本地缓存可能丢过），没有删除，请确认后手动清理"
            _LOGGER.warning("Kept statistics of replaced device %s: they exceed the new totals", old)
    await runtime.store.async_save(runtime.data)

    await _async_update_totals(hass, payload["start"], payload["end"], _retired_ids(runtime))
    await instance.async_block_till_done()
    await async_refresh_dashboard(hass, runtime)
    return result


def _retired_ids(runtime: Runtime) -> set[str]:
    return {i for device in runtime.data.get("retired", []) for i in _statistic_ids(device)}


async def _async_clear_if_covered(hass: HomeAssistant, old: str, latest: list[int]) -> bool:
    """新 id 的累计不少于旧 id 才删旧的：本地缓存丢过时，HA 里的旧数据可能是唯一一份。"""
    instance = get_instance(hass)
    ids = _statistic_ids(old)
    stats = await instance.async_add_executor_job(
        statistics_during_period, hass, EPOCH, None, set(ids), "month", None, {"sum"}
    )
    for statistic_id, kind, total in zip(ids, KINDS, latest, strict=True):
        if (rows := stats.get(statistic_id)) and (rows[-1]["sum"] or 0) > total / UNITS[kind][0] + 1e-6:
            return False
    if stats:
        instance.async_clear_statistics(ids)
    return True


async def _async_update_totals(hass: HomeAssistant, start: datetime, end: datetime, exclude: set[str]) -> None:
    """全部电脑合计 = 每个整点各电脑累计值之和。

    只重算这次推送覆盖的时段就够了：哪台电脑的数据变了，它推送时会把受影响的时段重算一遍。
    """
    instance = get_instance(hass)
    listed = {s["statistic_id"] for s in await async_list_statistic_ids(hass, statistic_type="sum")}
    hosts = {
        i: n
        for i in listed
        for n, kind in enumerate(KINDS)
        if i.startswith(f"{DOMAIN}:{kind}_") and i not in exclude
    }
    if not hosts:
        return

    def query(start_time: datetime, end_time: datetime | None, period: str):
        return statistics_during_period(hass, start_time, end_time, set(hosts), period, None, {"sum"})

    # 按月汇总不带结束时间，最后一个月的 sum 就是最新累计值
    months = await instance.async_add_executor_job(query, EPOCH, None, "month")
    total_ids = [f"{TOTAL_SOURCE}:{kind}" for kind in KINDS]
    if not listed & set(total_ids):
        # 第一次生成合计，从所有电脑里最早的数据算起
        if firsts := [rows[0]["start"] for rows in months.values() if rows]:
            first = dt_util.utc_from_timestamp(min(firsts)).replace(minute=0, second=0, microsecond=0)
            start = min(start, first)
    during = await instance.async_add_executor_job(query, start, end + HOUR, "hour")

    times = []
    t = start
    while t <= end:
        times.append(t)
        t += HOUR
    totals = [[0.0] * len(times) for _ in KINDS]
    for statistic_id, n in hosts.items():
        rows = [r for r in during.get(statistic_id, []) if r.get("sum") is not None]
        # 每台电脑推的小时数据从第一次有用量起是连续的：这段时间里有数据，前面缺的就是还没开始用；
        # 一条都没有，说明它在这段时间之前就停推了，沿用它最后的累计值
        last = 0.0 if rows else ((months.get(statistic_id) or [{}])[-1].get("sum") or 0.0)
        by_hour = {r["start"]: r["sum"] for r in rows}
        for j, t in enumerate(times):
            last = by_hour.get(t.timestamp(), last)
            totals[n][j] += last
    for n, kind in enumerate(KINDS):
        _import(hass, total_ids[n], f"{TOTAL_NAME} {LABELS[kind]}", kind, zip(times, totals[n], strict=True))


async def async_refresh_dashboard(hass: HomeAssistant, runtime: Runtime) -> None:
    retired = _retired_ids(runtime)
    names = {
        s["statistic_id"]: s.get("name") or s["statistic_id"]
        for s in await async_list_statistic_ids(hass, statistic_type="sum")
        if s["statistic_id"].startswith(DOMAIN + ":") and s["statistic_id"] not in retired
    }
    await dashboard.async_update(hass, names)
