---
name: 配置仓库 secret（运维任务）
about: 申请持有者给本仓配置 CI 用的 GitHub repo secret（如 KAS_READ_TOKEN、CR_RO_* / CR_PUSH_*）。值只经 gh secret set，不经信件、不进代码。
title: "[ops] 配置 secret: <SECRET_NAME>"
---

<!-- 母仓 aullik5/krow .github/ISSUE_TEMPLATE/configure-required-secret.md 在本仓的精简版。
     宪法 §0.2 E：以「对方不给 X」为前提做设计，必须附一次指名道姓的请求——这张单就是那次请求。 -->

## 目标 secret

**Secret 名**：`<SECRET_NAME>`

**类别**（勾选）：

- [ ] PR 必配：required check 要它才能真正跑（缺了 = 空绿，`scripts/lint_enforce_start.py` 的 `enforce-by` 到期转红）
- [ ] 构建 / 发布必配：`agent-image.yml` / `auto-tag-on-version-bump.yml` 要它
- [ ] 按需：缺失时对应步骤明确跳过并在 summary 里写明

**影响 workflow**（文件名 + job）：

- `<workflow>.yml` :: `<job name>`

## 当前状态

```bash
gh secret list -R Krow-labs/hikos-gamedev | grep <SECRET_NAME>
# 粘贴实际输出（只有名字和时间戳，不会显示值）：
```

- [ ] 未配置
- [ ] 已配置但需轮换 / 权限不够

## 配置步骤（持有者做）

```bash
# 值从持有者本机 / 密码管理器直接进 GitHub，不经聊天、不经信件、不进任何 git-tracked 文件
gh secret set <SECRET_NAME> -R Krow-labs/hikos-gamedev
gh secret list -R Krow-labs/hikos-gamedev | grep <SECRET_NAME>
```

对 `KAS_READ_TOKEN`：一个对 `Krow-labs/krow-agent-service` 只读（`contents: read`）的 fine-grained PAT 或机器人 token 即可；它只用于 `governance.yml::teammate plugin tests + K1–K9` 的 sparse-checkout。

## 验证（关单前）

- [ ] `gh secret list` 里有它
- [ ] 影响的 workflow 在 main 上手动 `gh workflow run` 一次：对应 job 真正跑了（log 里没有 "未配置 / skipped"）
- [ ] 若 `governance.yml` 里为它写过 `enforce-by:`，同 PR 把该步骤改回 enforce 并写 `enforce-by-done: <日期>`

## 注意

1. **永不**把明文 secret 贴进 issue / PR / 评论 / 站内信 / 大厅。
2. 推荐专属机器人账号 / 专属 token，审计轨迹干净、额度独立。
