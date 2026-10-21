# Changelog

## v0.4.0

## v0.3.5

优化 `gdeploy --commit`：fetch 后验证清单提交可用，再以 `git switch --detach <commit>` 检出快照，不移动本地分支；工作树有未提交修改时停止检出。
优化 `gdeploy`：清单未声明 `mode` 时按既有目标的实际布局（archive/mirror/bare/worktree）处理，避免对裸仓库执行 worktree 检出。
优化 `gdeploy`：`--commit` 缺少提交或本地对象库中找不到提交时明确报错，该仓库部署失败，不再报 `unable to read tree`。
优化 `gdeploy` archive 判定对齐 `garchive`，要求 `.git` 内存在 `config.archive`。
优化 `gdeploy` 部署时的 remote 校验：严格匹配清单中的 remote 名称；同名 URL 不一致或名称缺失时需确认同步，非交互模式可使用 `--sync-remotes`。
优化 `gdeploy` remote 同步提示：显示相对工作空间的仓库路径，并列出清单与本地 remote 的名称和 URL；即使 URL 相同也不再静默复用不同名称的 remote。
优化 `gdeploy --scan`：比较清单与本地 remote，冲突时交互确认；`--scan --sync-remotes` 批量采用本地 remote 更新清单，但仍需确认最终差异，且不修改本地 Git 配置。
优化 `gdeploy --scan` 对游离 HEAD 的处理：始终记录当前提交；若该提交属于清单分支则保留分支记录，否则写入 `branch: None`，并给出明确警告。

## v0.3.4

修复 `gwalk` 遇到 bare、mirror 和 `garchive` archive mirror 仓库时执行 `git status` 报错的问题，并显示对应的 clean 类型。
新增 `gl -f/--fetch` 安全抓取模式，禁用 fetch 的后台 maintenance，并在前台主动执行维护；bare/archive mirror 仓库非 quick 模式统一使用该流程。
新增 `garchive clone`，为 gdeploy 创建带 `config.archive` 和 `mate.archive` 的 archive mirror。
新增 `garchive archive --clean` 清理工作目录，`--force` 跳过被忽略文件的确认。
优化 `garchive restore --path` 支持指定父目录：含真实 `.git` 目录且未指定 `--name` 时自动原地还原；`.git` 为 gitdir 文件（worktree）时报错。
优化 `garchive restore --checkout` 不带分支时使用当前 `HEAD` 分支。
优化 `garchive` 使用位置参数 `archive`/`restore` 替代 `--archive`/`--restore`。
优化 `garchive` 使用固定 `config.archive` 归档原始 config，`restore` 检测到则还原并保留原配置。
优化 `garchive` 参数 `--branch` 为 `--checkout`。

## v0.3.3

添加 `garchive` 工具, 支持普通仓库与 archive/mirror 仓库之间转换。
优化 `garchive` 命令行为 `--archive/--restore --path --name --remote --branch`。
添加 `garchive -H/--here`，支持 archive `.git` 仓库原地恢复为普通仓库。
添加 `gdeploy` 仓库 `mode`，支持 `archive`、`mirror`、`bare` 清单扫描和部署，并通过 `--checkout` 显式检出 archive 仓库。

## v0.3.2

添加 `gdeploy` 选项 `--listed` 支持仅扫描并更新清单中已存在的仓库。
优化 `gdeploy` 选项 `--remote` 支持多个远程源, 为一个优先级列表, 顺序选择第一个存在的 remote。

## v0.3.1

完善 `gwalk`、`gapply`、`gcp`、`gl` 的测试覆盖，补充仓库遍历、状态匹配、过滤器、命令生成、dry-run、失败处理等场景。
修复 `gcp` 和 `gl` 对 `exit()` 的依赖，改为显式使用 `sys.exit()`。
修复 `RepoWalk.isRepo()` 在路径不存在时抛出异常的问题，现在返回 `False`。
优化 Git 子模块的处理

## v0.3.0

重构 `gdeploy` 为基于 manifest 的工作空间部署工具。
添加 `gdeploy --scan`，支持扫描工作空间并合并更新 `gdeploy.manifest`，写入前显示规范化后的差异并确认。
添加 `gdeploy` 命名 remote、变量替换、部署后 `post` 命令、`-H/--here` 原地部署、`--remote` 远程选择、`--commit` 固定提交部署。
扫描 manifest 时记录仓库 `commit` 和 `describe`，并对 dirty 仓库输出警告。
添加 `gdeploy`、`gapply`、`gwalk`、`gcp`、`gl` 的 PR 规则文档。

## v0.2.9

添加 `gwalk -t/--test <cmd>` 过滤选项。

## v0.2.8

修复 unix-like 环境下不正确的处理换行符问题
优化 bash 终端体验, 不跳过 `.bashrc` 用户配置

## v0.2.7

添加 gwalk 对游离状态的支持
修复 gwalk -j 选项，默认参数逻辑处理错误的问题

## v0.2.6

添加 `gwalk -j` 选项，允许 `gwalk -a run` 多个任务并发运行, 减少等待时间
优化 `gwalk -a bash` 交互模式下的命令提示符

## v0.2.5

添加 `gapply -D` 选项，允许应用后不提示地删除补丁文件
添加 `gapply -j` 选项，允许应用后随机等待一小会儿

## v0.2.4

修复 gapply 应用补丁时关于主题提取、补丁应用方面的bug
添加 `gapply -d` 选项，允许应用后删除补丁文件

## v0.2.3

重构 gapply 工具，允许自动检测补丁中的新文件, 并创建完整的提交
优化 gl/gcp 工具，允许工作在非仓库根目录
优化 命令行接口，使之更加清晰
