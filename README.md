# gwalk

![Version](https://img.shields.io/pypi/v/pygwalk)
![Python](https://img.shields.io/pypi/pyversions/pygwalk)
![License](https://img.shields.io/github/license/ZeroKwok/gwalk)

gwalk 一个用于管理批量 Git 仓库的命令行工具集，帮助开发者对大批量的 Git 仓库进行日常维护。

## ✨ 特性

- 🔍 列出指定目录下的 Git 仓库(可选递归)
- 🎯 支持按状态过滤(modified/untracked/dirty/clean)
- 📋 支持黑/白名单过滤
- 🚀 支持批量执行命令
- 🔄 集成常用 Git 操作的小工具

## 📦 安装

### 通过 pip 安装

```bash
python -m pip install pygwalk
```

### 从源码安装

```bash
git clone https://github.com/ZeroKwok/gwalk.git
cd gwalk
python -m pip install .
```

## 🔨 命令行工具

### gl - Git Fetch & Pull

快速执行 fetch 和 pull 操作:

```bash
# 拉取所有远程仓库并合并到当前分支
gl

# 使用 rebase 模式拉取
gl --rebase

# 仅执行 pull (跳过 fetch)
gl -q
```

### gcp - Git Commit & Push

快速提交并推送更改:

```bash
# 提交修改并推送到所有远程仓库, 等价于
# git add -u && git commit -m "your commit message" && git push
gcp "your commit message"

# 仅推送当前分支到所有远程仓库
gcp -p
```

### gwalk - 仓库批处理工具

用于批量管理 Git 仓库:

```bash
# 列出当前目录下的所有 dirty 仓库
gwalk

# 递归列出当前目录下的所有仓库
gwalk -rf all

# 在所有列出的仓库中执行 git fetch && git pull
gwalk -rf all -a run gl
```

### gdeploy - 用清单管理 Git 工作区

```bash
# 对比当前项目的 gdeploy.manifest 与本地仓库，不抓取、不写入
gdeploy --diff

# 指定项目根目录，并以清单中的 github 远端优先判断未推送提交
gdeploy --diff -d PROJECT --remote github

# 按清单检出当前工作区，跳过已完全匹配或当前 HEAD 已领先的仓库
gdeploy --commit --skip-local-ahead -H
```

检查结果显示提交匹配、领先或分叉，以及未提交修改和相对于本地远端缓存的未推送提交。详见 [`gdeploy` 规则](doc/PR-gdeploy.md#read-only-comparison)。

### gapply - 补丁应用工具

应用补丁并创建提交(dry-run 模式):

```bash
gapply -n patchs/0008-Add-cache-and-Settings-management-capabilities-suppo.patch 
```

输出如下:

```bash
Patch: patchs/0008-Add-cache-and-Settings-management-capabilities-suppo.patch
 - subject : Add cache and Settings management capabilities, supportfor environment detection
 - newfiles: 
  - src/shared/store/cache.js
  - src/shared/store/preset.js
  - src/shared/store/settings.js
  - src/shared/utils/env.js
(dry-run) > git apply -v "patchs/0008-Add-cache-and-Settings-management-capabilities-suppo.patch"
(dry-run) > git add -u
(dry-run) > git add "src/shared/store/cache.js"
(dry-run) > git add "src/shared/store/preset.js"
(dry-run) > git add "src/shared/store/settings.js"
(dry-run) > git add "src/shared/utils/env.js"
(dry-run) > git commit -m "Add cache and Settings management capabilities, supportfor environment detection"
```

## 📝 使用示例

```bash
# 在所有 gwalk 列出的仓库中, 执行 gl 工具(git pull)
gwalk -rf all -a run gl

# 在所有 gwalk 列出的仓库中, 执行 git push 操作 {ab} 表示 当前分支(ActiveBranch)
gwalk -rf all -a run git push second {ab}

# 批量手动处理(交互模式)
# 在列出的所有 '包含未提交的修改' 的仓库中, 启动一个 bash shell 来接受用户的操作
gwalk -rf modified --a bash

# 批量推送
# 在列出的所有 '包含未提交的修改 且 不再黑名单中' 的仓库中, 运行 gcp 工具, 推送当前分支到所有远程仓库
gwalk -rf modified --blacklist gwalk.blacklist --a "gcp -p"

# 批量打标签
# 在列出的所有 白名单 gwalk.whitelist 匹配的仓库中, 运行 git tag v1.5.0
gwalk -rf all --whitelist gwalk.whitelist -a run git tag v1.5.0

# 批量查看目录下所有仓库的最近3次提交
gwalk -f all -l none -a run "git log --oneline -n3"

# 批量替换 origin 远程仓库的地址, 从 github.com 替换成 gitee.com
# 在所有 gwalk 列出的仓库中, 执行自定义命令
gwalk -rf all -a run git remote set-url origin `echo \`git remote get-url origin\` | python -c "print(input().replace('github.com', 'gitee.com'))"`
```

## 📄 协议

本项目基于 MIT 协议开源 - 详见 [LICENSE](LICENSE) 文件
