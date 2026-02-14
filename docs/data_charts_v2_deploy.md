# 数据图表 WebEngine 页面部署/运行要点

## 依赖
- PyQt6 + QtWebEngine（用于 QWebEngineView）
- 项目自带 ECharts 资源文件：
  - `data/echart/echarts.min.js`

## 数据库
- 默认通过 `BirdLibraryDB` 打开用户数据库路径（Settings/PathManager 控制）。
- 若出现 “数据库不可用”，请优先检查：
  - 用户数据库路径是否可读写
  - 目录是否存在、权限是否正常
  - SQLite 文件是否被占用/损坏

## 资源加载
- 页面通过 `setHtml(html, baseUrl=项目根目录)` 加载：
  - `qrc:///qtwebchannel/qwebchannel.js`
  - `data/echart/echarts.min.js`
- 若 ECharts 未加载，优先确认 `data/echart/echarts.min.js` 是否存在。

