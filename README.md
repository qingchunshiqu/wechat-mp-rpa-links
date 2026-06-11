# WeChat MP RPA Links

一个基于 Playwright 的微信公众号后台文章链接采集示例，用于学习浏览器自动化、会话复用、分页读取和本地内容归档流程。

> 仅用于学习、研究和合法授权场景。使用前请阅读 [风险声明](DISCLAIMER.md)。

## 功能

- 通过微信公众号后台搜索目标账号并读取历史文章。
- 支持按名称和微信号匹配目标账号。
- 支持导出 JSON 结果，保存文章标题、日期和链接。
- 支持下载文章 HTML 与图片资源到本地目录。
- 支持 `--since`、`--until` 限制时间范围。
- 支持本机 Chrome 或 Edge。
- 支持 `crawl_tasks.json` 批量配置定时任务。

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

## 快速开始

首次运行建议打开可视浏览器扫码登录：

```powershell
python wechat_mp_rpa_links.py "目标公众号" 2 --wechat-id gh_xxxxx --browser-channel chrome -o output.json
```

后续可使用 headless 模式：

```powershell
python wechat_mp_rpa_links.py "目标公众号" 2 --wechat-id gh_xxxxx --headless --browser-channel chrome -o output.json
```

下载文章 HTML 和图片：

```powershell
python wechat_mp_rpa_links.py "目标公众号" 2 --wechat-id gh_xxxxx --headless --browser-channel chrome --download --download-dir downloads -o output.json
```

使用 Edge：

```powershell
python wechat_mp_rpa_links.py "目标公众号" 2 --wechat-id gh_xxxxx --headless --browser-channel msedge -o output.json
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `account` | 目标公众号名称 |
| `count` | 需要采集的文章数量 |
| `--wechat-id` | 可选，公众号微信号，用于精确匹配 |
| `--headless` | 无界面运行，要求本地会话仍然有效 |
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
    { "name": "目标公众号", "wechat_id": "gh_xxxxx", "max_articles": 10 }
  ],
  "download_articles": true,
  "download_dir": "downloads",
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

`daily_crawl.py` 会按当前时间自动计算半天时间段，并为每个账号输出采集结果。

## 合规提示

本项目仅用于学习浏览器自动化技术。请遵守平台规则、版权要求和相关法律法规，不要将本项目用于未授权采集、批量抓取、商业使用或内容分发。
