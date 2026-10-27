"""Claude Code 用量集成的常量。"""

from datetime import UTC, datetime, timedelta

DOMAIN = "claude_code"
TITLE = "Claude Code"

KINDS = ("input", "output", "cache_write", "cache_read")
LABELS = {"input": "输入", "output": "输出", "cache_write": "缓存写入", "cache_read": "缓存读取"}
# 原始数字位数太多不好读：输入量小用千，其余用百万
UNITS = {
    "input": (1e3, "K tokens", "千"),
    "output": (1e6, "M tokens", "百万"),
    "cache_write": (1e6, "M tokens", "百万"),
    "cache_read": (1e6, "M tokens", "百万"),
}
# 每台电脑一组 claude_code:<类型>_<设备 id>；合计用单独的来源，各电脑的统计列表里就不会混进它
TOTAL_SOURCE = "claude_code_total"
TOTAL_NAME = "全部电脑"
# 改了统计的格式（如单位）就加一，各电脑下次推送时会被要求全量重推
DATA_VERSION = 2

DASHBOARD = "claude-code"
DASHBOARD_ICON = "mdi:robot-outline"
# 设置里没有 claude-code 仪表盘时，集成自己提供一个，配置存在 .storage/lovelace.<这个 id>
DASHBOARD_STORAGE_ID = "claude_code_usage"
# 改了仪表盘布局就加一，下次推送时会把旧布局换掉
DASHBOARD_VERSION = 5
DASHBOARD_VERSION_KEY = "cc_usage_version"
# 历史页的日期选择器和图表靠这个 key 联动，不用默认 key，免得和能源面板的日期互相影响
DATE_COLLECTION = "energy_claude_code"

HOUR = timedelta(hours=1)
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
# 一次最多接收三年的小时数据，防止误传超大请求
MAX_HOURS = 3 * 366 * 24
