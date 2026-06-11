# WeChat MP RPA Links

一个基于 Playwright 的微信公众号后台文章链接采集示例，用于学习浏览器自动化、登录态复用、分页读取和本地内容归档流程。

> 仅用于学习、研究和合法授权场景。使用前请阅读 [风险声明](DISCLAIMER.md)。

## 功能

- 通过微信公众号后台搜索指定公众号并读取历史文章。
- 支持按公众号名称和微信号精确匹配目标账号。
- 支持导出 JSON 结果，保存文章标题、日期和链接。
- 支持下载文章 HTML 与图片资源到本地目录。
- 支持 `--since`、`--until` 限制时间范围。
- 支持本机 Chrome 或 Edge，避免 Playwright 浏览器包下载失败。
- 支持 `crawl_tasks.json` 批量配置每日抓取任务。

## 环境要求

- Python 3.11+
- Playwright 1.60.0
- 本机已安装 Chrome 或 Edge
- 可正常登录微信公众号后台的账号

安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果希望使用 Playwright 自带浏览器：

```powershell
python -m playwright install chromium
```

国内网络可以尝试镜像，但镜像可能滞后：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright"
python -m playwright install chromium
```

## 快速开始

首次运行建议打开可视浏览器扫码登录：

```powershell
python wechat_mp_rpa_links.py "人民日报" 2 --wechat-id rmrbwx --browser-channel chrome -o result.json
```

登录成功后会在本地生成 `mp_auth.json`。后续可使用 headless 模式：

```powershell
python wechat_mp_rpa_links.py "人民日报" 2 --wechat-id rmrbwx --headless --browser-channel chrome -o result.json
```

下载文章 HTML 和图片：

```powershell
python wechat_mp_rpa_links.py "人民日报" 2 --wechat-id rmrbwx --headless --browser-channel chrome --download --download-dir articles -o result.json
```

使用 Edge：

```powershell
python wechat_mp_rpa_links.py "人民日报" 2 --wechat-id rmrbwx --headless --browser-channel msedge -o result.json
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `account` | 公众号名称，例如 `人民日报` |
| `count` | 需要采集的文章数量 |
| `--wechat-id` | 可选，公众号微信号，用于精确匹配 |
| `--headless` | 无界面运行，要求 `mp_auth.json` 仍然有效 |
| `--browser-channel` | 使用本机浏览器，例如 `chrome` 或 `msedge` |
| `--browser-executable` | 指定浏览器可执行文件路径 |
| `--download` | 下载文章 HTML 和图片 |
| `--download-dir` | 下载目录 |
| `--since` | 只采集该时间之后的文章，例如 `2026-06-10 09:00` |
| `--until` | 只采集该时间之前的文章 |
| `--scan-limit` | 时间筛选模式下最多扫描页数 |

## 批量任务

编辑 `crawl_tasks.json`：

```json
{
  "accounts": [
    { "name": "人民日报", "wechat_id": "rmrbwx", "max_articles": 10 }
  ],
  "download_articles": true,
  "download_dir": "daily_articles",
  "headless": false,
  "browser_channel": "chrome",
  "max_count": 30,
  "scan_limit": 50
}
```

运行：

```powershell
python daily_crawl.py
```

`daily_crawl.py` 会按当前时间自动计算半天时间段，并把每个账号的结果写入 `daily_crawl_results/`。

## 敏感文件

以下文件和目录默认不会提交到 Git：

- `mp_auth.json`
- `result.json`
- `articles/`
- `daily_articles/`
- `daily_crawl_results/`
- Python 虚拟环境和缓存目录

`mp_auth.json` 保存登录态 Cookie，泄露后可能导致账号风险。不要上传、转发或共享该文件。

## 合规提示

本项目仅用于学习浏览器自动化技术。请遵守平台规则、版权要求和相关法律法规，不要将本项目用于未授权采集、批量抓取、商业使用或内容分发。
