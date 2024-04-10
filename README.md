# gwalk

`gwalk` 是一系列用于管理 Git 仓库的命令行小工具，帮助开发者对大批量的 Git 仓库进行日常维护。

## 模块

### gwalk.py

`gwalk.py` 是 `gwalk` 工具的主要模块，提供了以下功能：

- 列出指定目录下的所有 Git 仓库，支持过滤条件、黑名单、白名单和递归搜索。
- 显示列出的仓库的状态信息，支持输出信息的简短或冗长格式。
- 可指定在每个列出的仓库中执行的任务，如运行自定义命令。

```bash
# 列出当前目录下所有的'脏'的 Git 仓库
gwalk.py

# 递归列出当前目录下所有的 Git 仓库
gwalk.py -rf all

# 在列出的每个仓库中执行命令: git pull origin
gwalk.py -rf all -a "run git pull origin"
```

### gcp.py

`gcp.py` 是用于执行 `git commit` 和 `git push` 操作快捷工具。

```bash
# 添加未跟踪的文件以及已修改的文件，并提交到远程仓库, 等价于下面的命令 
# git add -u && git commit -m "fix some bugs" && git push
gcp.py "fix some bugs"

# 仅推送当前分支到所有远程仓库，不进行提交
gcp.py --push
```

### gl.py

`gl.py` 是 `git pull` 的快捷工具。

```bash
# 从远程仓库拉取代码并合并到当前分支, 等价于下面的命令 
# git pull {origin 或 第一个remotes} {当前分支}
gl.py

# git pull {origin 或 第一个remotes} {当前分支} --rebase
gl.py --rebase
```

## 使用技巧

```bash
# 批量更新所有仓库
gwalk.py -rf all -a run gl.py

# 批量推送所有仓库的当前分支到 second 远程仓库
gwalk.py -rf all -a run git push second {ActiveBranch}

# 列出所有 '包含未提交的修改'的仓库, 并进入一个新的bash命令模式
gwalk.py -rf modified --a bash

# 列出所有 '包含未提交的修改 且 不再黑名单中' 的仓库, 并执行 gcp.py 命令, 为每个仓库输入提交信息
gwalk.py -rf modified --blacklist gwalk.blacklist --a gcp.py

# 批量打标签(白名单 gwalk.whitelist 匹配的仓库)
gwalk.py -rf all --whitelist gwalk.whitelist -a run git tag release_v1.5.0

# 批量替换 origin 远程仓库的地址, 从 github.com 替换成 gitee.com
gwalk.py -rf all -a run git remote set-url origin `echo \`git remote get-url origin\` | python -c "print(input().replace('github.com', 'gitee.com'))"`
```
