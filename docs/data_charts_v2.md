# 数据图表页面（WebEngine 重构版）

## 目标与范围
- 数据图表页使用 WebEngine 渲染 HTML/CSS/JS 界面，按钮与交互统一由前端实现。
- 后端用一个统一管理类集中处理：数据获取、处理、校验、异常处理与响应生成。
- 前后端通过 QWebChannel 双向通信，具备令牌校验与请求签名校验。

## 核心模块
- 页面入口：[data_charts_page.py](file:///d:/code/BirdPictureManager/table/data_charts_page.py)
- HTML 模板：[data_charts_html.py](file:///d:/code/BirdPictureManager/table/web/data_charts_html.py)
- 后端管理器：[charts_backend_manager.py](file:///d:/code/BirdPictureManager/table/web/charts_backend_manager.py)
- 通信桥：[charts_web_bridge.py](file:///d:/code/BirdPictureManager/table/web/charts_web_bridge.py)

## 架构与数据流
1. 页面创建 WebEngine 与 QWebChannel，并注册 `bridge` 对象。
2. HTML 初始化后通过 `bridge.getToken()` 获取会话令牌。
3. 前端对每个请求执行 HMAC-SHA256 签名（action + "\n" + payload），调用 `bridge.request(...)`。
4. 后端校验 token + 签名，通过后调用管理器方法，返回 JSON 字符串。
5. 前端根据返回的 `payload.kind` 渲染 ECharts 或图片列表，并显示加载/错误状态。

## 真实数据来源
- 默认读取本地 SQLite 数据库（BirdLibraryDB）：
  - 图片库：`bird_results`
  - 导入数据：`import_cache`
- 主要字段：`score/iso/shutter/fnumber/focal_length/shot_time/created_at/order_cls/family_cls/genus_cls/species_cls/latitude/longitude/...`

## 持久化
- 布局/图表列表/设置保存到：`data/cache/charts_layout_v2.json`

## 安全与校验
- 会话令牌：后端生成随机 token，前端首次读取。
- 请求签名：前端使用 WebCrypto 做 HMAC-SHA256，后端使用标准库 hmac/sha256 校验。
- 数据库不可用时：后端不抛出到 UI，前端显示“数据库不可用”并禁用按钮。

