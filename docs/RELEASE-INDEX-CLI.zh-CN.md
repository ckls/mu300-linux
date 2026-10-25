# 发行包 JSON 摘要工具

`OpenWrt-Release-Index.exe` 是独立的 Windows x64 命令行程序，不需要安装 Python、WSL 或 Diff Studio。E5 系列和 MU300 系列共用一份工具。

## 最简单的用法

把成品 ZIP 拖到 EXE 上。程序检查包内校验值、读取文件清单和哈希，在 ZIP 旁边导出 `.owrt-index.json`。它会显示分析进度和输出位置；拖入文件打开的窗口完成后等待回车退出。

也可以直接运行：

```powershell
.\OpenWrt-Release-Index.exe "D:\Releases\e5-openwrt-25.12.5-xxx.zip"
.\OpenWrt-Release-Index.exe "D:\Releases\mu300-openwrt-xxx.zip" -o "D:\Releases\old.json" --no-pause
```

## 批量目录

也可以直接传入存放一批发布包的目录：

```powershell
.\OpenWrt-Release-Index.exe .\data\
.\OpenWrt-Release-Index.exe .\data\ --jobs 4
.\OpenWrt-Release-Index.exe .\data\ -o .\indexes\ --no-pause
```

默认同时处理 2 个包，`--jobs 4` 或 `-j 4` 可指定并发数，`--jobs 1` 切换为串行；不会一次把所有包加载到内存。每个任务拥有独立的读流和 16 MiB gzip 缓存，同名输出的检查与原子提交会串行执行：相同内容复用，不同内容报错而不覆盖。Ctrl+C 会取消排队任务，正在分析的任务在下一次文件进度检查时退出，保留此前完成的摘要。

程序递归查找 ZIP、裸 rootfs 镜像和完整解压包，显示当前包序号及文件分析进度；完整解压包作为一个输入，不再重复处理其内部载荷，单独的 boot 镜像不会被当成 rootfs。默认摘要保存在各输入旁边，`-o` 可指定统一的输出目录。

某个包失败会标明文件名并继续其余包，最后汇总成功和失败数；有失败时进程返回 1，全部成功返回 0。重复运行会复用内容一致的摘要，不覆盖不同内容的现有文件。批量模式不接受单一 `--boot`，避免把同一启动镜像套给不同机型。

默认文件名包含机型、OpenWrt 版本、内核版本及原发布标识。例如：

`OpenWrt-index-e5-25.12.5-k6.18.54-r20261025.181536-g831cd7b4-sd58c2ece.owrt-index.json`

同一摘要重复生成可复用原文件；目标存在其他内容时不会覆盖。

## 如何分发、生成更新

1. 为每个正式发布包保留一份对应摘要，随版本说明上传到网站。
2. 用户下载旧版摘要和新版完整 ZIP。
3. 打开现有 Diff Studio，旧版选择 JSON，新版选择完整 ZIP，分析后生成更新包。

摘要格式与现有 Diff Studio 的“导出版本摘要”一致，不需要更改设备 OTA 插件。旧版原包可以移走；新版完整包仍负责提供实际更新文件。摘要不包含文件正文、rootfs 或 boot 内容，只含版本身份、文件描述与哈希、权限、符号链接、扩展属性、软件包元数据和 boot 哈希。

## 裸 rootfs

自动识别 tar、tar.gz/tgz、ext4 镜像及 gzip 压缩的 ext4。无需解压根目录、挂载镜像或通过 WSL 处理；gzip 随机访问缓存限制为 16 MiB。

裸 rootfs 必须内含版本身份 `/etc/e5/release.json` 或 `/etc/mu300/release.json`，才能区分机型及准确版本。工具优先自动读取同目录唯一的 `boot.img` 或 `boot-linux.img`；也可明确提供：

```powershell
.\OpenWrt-Release-Index.exe "D:\Releases\openwrt.ext4.gz" --boot "D:\Releases\boot.img"
```

没有旧版 boot 也可导出摘要：`boot_digest` 的全零值明确表示未提供，而不是声称原 boot 的哈希为零。现有 Diff Studio 会据此将新版完整 boot 放入差异包，不会漏掉启动镜像。完整 ZIP 的实际 boot 哈希按包内校验值核实后写入摘要。

## 源码与构建

源码：`tools/release-index.py`。现有索引校验及 JSON 写入复用 `installer/backend/release_index.py`；完整包容器读取和哈希校验复用 Diff Studio 后端。程序不会连接设备、调用 ADB、联网、修改输入或读取实机数据。

使用已有本地 Windows Python、PyInstaller 和 `installer/ota-requirements.txt` 中的依赖，通过本仓库构建入口记录日志：

```powershell
wsl -d Ubuntu-22.04 --cd /mnt/d/Git/e5-linux --exec python3 tools/build-release.py run --workspace /home/kano/openwrt-build --label release-index-cli -- /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command 'Set-Location -LiteralPath D:\Git\e5-linux; & C:\Python312\python.exe tools/build-release-index.py; exit $LASTEXITCODE'
```

MU300 在其仓库执行相同的入口和构建脚本；不会另建 Linux 编译环境或复制系统镜像。成品为一个 EXE，旁边的 `build.json` 和 `.sha256` 仅供发布核对，不是运行依赖。

回归覆盖摘要与原 Diff Studio 文件表一致、旧包移走后仍能出补丁、权限/链接/扩展属性保留、裸镜像识别、实际 ext4、中文路径、重复导出与失败不覆盖。
