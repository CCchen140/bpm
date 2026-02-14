# 数据图表页面重构测试报告（最小集）

## 覆盖范围
- 主窗口首次点击“数据图表”进入时不再显示奖章页（索引漂移修复）
- WebChannel 通信接口可用：bootstrap/add/remove/get_payload
- 数据库不可用时的降级：页面可加载、按钮禁用、提示可见

## 自动验证
- 脚本：[verify_data_charts_web.py](file:///d:/code/BirdPictureManager/scripts/verify_data_charts_web.py)
  - 断言：chart_types 数量为 24
  - 断言：bridge token 可生成
  - 断言：数据库打不开时不崩溃（返回 db_ready=false）

## 手工验证建议
- 启动主程序，点击侧边栏“数据图表”：
  - 首次进入显示“数据图表”界面，不闪到奖章页
  - 点击“添加图表”后，选择类型/字段，创建后可渲染图表
  - 点击“刷新”能重新拉取并重绘
  - 断开/破坏数据库路径时显示“数据库不可用”，按钮禁用

