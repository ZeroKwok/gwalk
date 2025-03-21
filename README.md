# gwalk

`gwalk` 是一系列用于管理 Git 仓库的命令行小工具，帮助开发者对大批量的 Git 仓库进行日常维护。

## 安装

### 1. pip

1. `python -m pip install pygwalk`

### 2. build from source

1. `git clone https://github.com/ZeroKwok/gwalk.git`
2. `cd gwalk`
3. `python -m pip install .`

## 使用

### 1. gl

`gl.py` 是 `git pull` 操作的快捷工具。

```bash
# 从远程仓库拉取代码并合并到当前分支, 等价于下面的命令 
# git pull {origin 或 第一个remotes} {当前分支}
gl

# git pull {origin 或 第一个remotes} {当前分支} --rebase
gl --rebase
```

### 2. gcp

`gcp.py` 是用于执行 `git commit` 和 `git push` 操作快捷工具。

```bash
# 添加未跟踪的文件以及已修改的文件，并提交到远程仓库, 等价于下面的命令 
# git add -u && git commit -m "fix some bugs" && git push
gcp "fix some bugs"

# 仅推送当前分支到所有远程仓库，不进行提交
gcp -p
```

### 3. gwalk

`gwalk.py` 是 `gwalk` 工具的主要组件，提供了以下功能：

- 列出目录下的所有 Git 仓库，支持过滤条件、黑名单、白名单和目录递归。
- 显示列出的仓库的状态信息，支持输出信息的简短或冗长格式。
- 在每个列出的仓库中执行一个操作。如运行自定义命令: 类似于子仓库操作 `git submodule foreach 'some command'` 但更加灵活。

```bash
# 列出当前目录下所有的'脏'的 Git 仓库
gwalk

# 递归列出当前目录下所有的 Git 仓库
gwalk -rf all

# 在列出的每个仓库中执行命令: git pull origin
gwalk -rf all -a "run git pull origin"
```

## 使用技巧

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
