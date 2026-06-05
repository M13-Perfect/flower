# Project Instructions for Codex

## 项目目标

这是一个本地桌面应用，用于根据订单备注或人工输入生成 Birth Flower 个性化图片。

核心原则：

1. 动态识别只用于提高效率，最终生成必须人工确认。
2. 不允许识别后自动生成最终文件。
3. 代码要跨平台，优先支持 Windows、macOS、Linux。
4. 不要内置商业字体，不要下载字体。
5. 不要假设用户素材一定存在，所有文件缺失都要友好报错。
6. SVG 如果嵌入的是 PNG/JPG 花朵素材，需要明确提示这不是纯矢量。
7. 复杂文字排版需要提示 RAQM 支持风险。
8. 所有关键逻辑请加中文注释。
9. 新增功能必须配套测试。
10. 不要无必要更换 UI 框架。

## 推荐模块拆分

- birth_flower_mvp.py：程序入口
- ui_app.py：界面逻辑
- birth_flower_parser.py：订单备注解析
- asset_resolver.py：素材和字体路径解析
- renderer.py：PNG 和 SVG 渲染
- config_store.py：配置读写
- models.py：数据结构
- tests/：pytest 测试

## 质量要求

- 使用 pathlib.Path 处理路径
- 使用 dataclass 管理结构化数据
- 捕获常见异常
- README 必须同步更新
- requirements.txt 必须同步更新
- pytest 必须通过