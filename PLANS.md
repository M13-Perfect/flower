# Execution Plans

For significant refactors, Codex must create an execution plan before editing many files.

Each plan must include:

1. Goal
2. Current code findings
3. Proposed architecture
4. File changes
5. Data model changes
6. API changes
7. Test plan
8. Risks
9. Rollback plan
10. Milestones

Codex should update the plan after each milestone.
Codex should not perform a broad rewrite without a written plan.

## Active plans

- [可引用字段系统（Reference Field System）](docs/superpowers/plans/2026-06-23-reference-field-system.md) — 把管理员端写死的 info1/2/3 + 整体拼接背景提示词，升级为「稳定 ID + 不可变序号 + `/` 引用 + 原位展开 + 双视图预览」。设计待评审，§19 有 3 项待用户拍板。