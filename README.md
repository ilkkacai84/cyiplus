# 汇率查询与推送工具

纯 Python 3 命令行工具，从 `smbs.biz` 和中国外汇交易中心获取汇率，支持表格、JSON 和 HTTP POST 推送。不依赖第三方 Python 库。

## 功能

- 获取外币兑韩元牌价。
- 获取人民币汇率中间价。
- 支持指定日期，优先级为命令行、配置文件、当天。
- 网络请求失败时最多重试 5 次，每次间隔 60 秒。
- SMBS 无有效汇率时停止输出和推送，避免发送空数据。
- Chinamoney 非交易日无数据时自动跳过。

## 环境

- Python 3.6+
- macOS、Linux 或 Windows

## 配置

复制示例配置：

```bash
cp config.example.json config.json
```

`config.json` 包含查询日期和推送 API 配置：

```json
{
  "date": "",
  "push_api": {
    "url": "http://127.0.0.1:8080/api/exchange-rates",
    "method": "POST",
    "headers": {
      "Content-Type": "application/json"
    },
    "timeout": 15
  }
}
```

`date` 留空表示使用当天。当前推送协议只支持 JSON POST。本地 `config.json` 不会提交到 Git。

## 使用

```bash
# 表格输出
python3 exrate.py

# JSON 输出
python3 exrate.py --json

# 推送到配置的 API
python3 exrate.py --push

# 指定日期
python3 exrate.py --date 2026-07-18 --json
```

`--json` 和 `--push` 不能同时使用。Windows 可直接运行对应的 `.bat` 文件。

## JSON 格式

```json
{
  "date": "2026-07-18",
  "smbs": [
    {"from_currency": "USD", "to_currency": "KRW", "rate": 1510.0}
  ],
  "chinamoney": [
    {"from_currency": "USD", "to_currency": "CNY", "rate": 7.2}
  ]
}
```

`rate` 始终为 JSON 数值。Chinamoney 无数据时不输出 `chinamoney` 字段。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## Windows EXE

在 Windows 上运行 `build_exe.bat`，脚本会安装 PyInstaller 并生成 `exrate.exe`。`config.json` 需放在 EXE 同目录。

## 主要文件

```text
exrate.py              主程序
config.example.json    配置示例
tests/test_exrate.py   离线单元测试
exrate.bat             Windows 表格模式
exrate_json.bat        Windows JSON 模式
exrate_push.bat        Windows 推送模式
build_exe.bat          Windows EXE 打包脚本
```
