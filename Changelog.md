# Changelog

## v0.3.3

添加 `garchive` 工具, 支持普通仓库与 archive/mirror 仓库之间转换。
优化 `garchive` 命令行为 `--archive/--restore --path --name --remote --branch`。
添加 `garchive -H/--here`，支持 archive `.git` 仓库原地恢复为普通仓库。

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
