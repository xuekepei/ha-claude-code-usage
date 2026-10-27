# Claude Code Usage for Home Assistant

把多台电脑上 Claude Code 的 token 用量汇总到 Home Assistant 的长期统计，并自动生成仪表盘。

- 每台电脑上的推送脚本每小时读本机 `~/.claude/projects` 下的会话日志，把按小时的 token 数 POST 到这个集成的 webhook。
- 集成把数据导入外部统计 `claude_code:<类型>_<设备 id>`（类型为 `input` / `output` / `cache_write` / `cache_read`），并维护全部电脑的合计 `claude_code_total:<类型>`。
- 侧边栏的「Claude Code」仪表盘有两个视图：「概览」按天和按周显示，「历史」可以按日期范围查看。出现新电脑时，图表会自动加上它。
- 电脑上不需要 HA 令牌。webhook 只接受下面这种格式的用量数据，所以地址泄漏的后果仅限于被写入假用量；需要时可以在集成的「重新配置」里换一个地址。

## 安装

1. HACS → 右上角菜单 → 自定义存储库，添加本仓库，类别选 Integration，然后下载。
2. 重启 Home Assistant。
3. 设置 → 设备与服务 → 添加集成 → Claude Code Usage，完成后会显示 webhook 地址。以后可以在该集成的「重新配置」里再看到它。
   HA 没有设置外部地址（设置 → 系统 → 网络）时，这里只显示 `/api/webhook/...` 这段路径，需要在前面补上从外面访问 HA 的地址。

如果设置里已经有 URL 为 `claude-code` 的仪表盘，集成会沿用它；没有就自己提供一个。仪表盘布局只在两种情况下重新生成：布局版本更新，或者有电脑还没出现在图表里。

## 推送格式

`POST <webhook 地址>`，`Content-Type: application/json`：

```json
{
  "device": "3f2a9c1b7d4e",
  "name": "MacBook-Pro",
  "start": "2026-10-20T09:00:00+00:00",
  "end": "2026-10-27T09:00:00+00:00",
  "base": [123456, 7890123, 4567890, 98765432],
  "hours": {"2026-10-20T10:00:00+00:00": [12, 3456, 7890, 123456]},
  "full": false,
  "replaces": "old_device_id"
}
```

- 数组里各类型的顺序固定为 input、output、cache_write、cache_read，单位是 token。
- `start` 到 `end`（含）都是 UTC 整点。`hours` 只列有用量的小时，没列出的小时算 0。`base` 是 `start` 之前的累计值。
- `full` 表示从这台电脑的第一条数据开始推。`replaces` 可选：设备 id 变了的时候填旧 id，集成会删掉旧 id 的统计（前提是新 id 的累计不比它少）。
- 成功时返回 `{"imported": <小时数>, "full_needed": <bool>}`。`full_needed` 为 true 时，说明集成这边没有这台电脑的完整历史（比如集成刚装好，或者统计格式改过），客户端要再发一次 `full: true` 的全量推送。
- 格式错误返回 400，内部错误返回 500。HA 对不存在的 webhook 也会返回 200 和空内容，所以客户端要检查返回里有没有 `imported`。

统计单位：input 用 K tokens，其余三类用 M tokens。

另有 `GET /api/claude_code/webhook`，需要管理员令牌，返回 `{"webhook_path": "/api/webhook/..."}`。旧版脚本靠它把配置里的 HA 令牌换成 webhook 地址，换完就删掉令牌。
