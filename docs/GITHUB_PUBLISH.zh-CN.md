# GitHub 仓库与发布

## 本项目的仓库

| 项 | 值 |
|---|---|
| 仓库 | <https://github.com/chinrw/chatgpt-linker> |
| 可见性 | **public** |
| 默认分支 | `main` |
| 创建方式 | 仓库所有者在 GitHub 上手工创建，本机未使用建仓脚本 |

日常更新就是普通推送：

```sh
git push origin main
```

远程状态的判断只依据 Git 远端实际返回的结果，例如 `git ls-remote origin` 能列出 `main`、GitHub 页面能看到对应 commit。本文档**不声称 GitHub Actions 已经通过**；以仓库的 Actions 页面为准。

### public 仓库的安全提醒

仓库是公开的，因此任何进入 Git 的内容都应视为已公开。`.gitignore` 已排除 `state/`、真实 policy、`.env`、`*.pem`、`*.key`、`.venv`、构建产物和 `__pycache__`；`.dockerignore` 还额外排除了文档与测试。但忽略规则不是加密，也不是数据防泄漏：推送前请检查 `git status`，并且不要把真实 policy、任务状态或 tunnel 凭据复制进项目目录。

## 另建一个私有仓库（可选）

`scripts/publish-github.sh` 与上面的仓库无关，它的用途是：从当前源码生成一份**白名单快照**，推送到一个**尚不存在的私有仓库**。适用于想把同一份源码放进另一个（例如 private 镜像）仓库的场景。

需要本机已安装并登录 GitHub CLI（`gh`）、Git、Python 3.11+：

```sh
gh auth login --hostname github.com
bash scripts/publish-github.sh <owner>/<new-repository-name>
```

脚本验证当前登录账号与 owner 一致，目标必须是不存在的新仓库。它默认 **private**，不提供隐式 public 模式。任何已存在仓库都会导致拒绝；不会改写你的已有项目。

执行过程：检查身份和目标 → 复制源码白名单到独立临时目录 → 运行同一份源码的测试 → 初始化新 Git history → 创建私有仓库并 push → 返回实际 URL/私有状态。

发布快照不包括 `.venv`、任务 state、private provenance、模型/tunnel 凭据或源目录的 `.git` history。原目录不会被 `git init`、修改 remote 或写全局 Git 配置。

GitHub CLI 的 repo-create 行为依据[官方手册](https://cli.github.com/manual/gh_repo_create)。若认证对 workflow 文件/新仓库权限不足，应在 GitHub 的正规登录/授权流程处理，不把 token 发到聊天。

## 失败与恢复

目标已存在时脚本保守停止；这也覆盖“上次已经创建仓库、后来 push 失败”的情况。检查实际仓库状态，确认是你要操作的那个仓库后，再自行决定恢复 push 或使用新名称；脚本不会删除远程仓库或 force-push。

仅当 GitHub 查询明确为 404 时才尝试创建；网络/权限异常不被当作“仓库不存在”。创建与 push 不是跨 GitHub 的原子操作，因此失败消息会明确提示可能留下已创建的空仓库。

成功后以脚本返回的真实 URL 克隆仓库进行后续开发。不要把本地交付 ZIP 中的说明当作“GitHub CI 已经通过”的证据；以实际 Actions 页面为准。
