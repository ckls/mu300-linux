# UFS 新机型适配指南

更新：2026-10-27。供 MU300、E5 两仓库的后续 Agent 使用；第一份实际案例是 U30 Air UFS 版，下一台计划调查 E5 仓库的畅行 60。

**这是一份方法与交接记录，不是所有 UFS 设备已获支持的声明。** 当前 UFS 驱动和公共存储层改动位于 MU300 工作区；本指南同步到 E5 不代表 E5 已经移植代码。畅行 60 尚未连接调查，不能预填其 SoC、UFS 控制器、扇区、槽位或加密情况。

## 先读与边界

1. 阅读本仓库 `AGENTS.md`、`docs/NEW-DEVICE-STOCK-ADAPTATION.zh-CN.md`；编译前再读 `docs/LOCAL-BUILD.zh-CN.md`、`docs/AGENT-BUILD.zh-CN.md`。
2. 用户明确禁止使用 fastboot。使用已确认设备的 ADB/root 通道；若此通道不可用，保留现场并说明，不擅自换启动协议。
3. 初始调查只读。临时写备用 boot 与启动控制、变更 GPT、格式化 userdata、写 NV 是不同操作，应按实际授权分别处理。适配授权不等于清空 Android 授权。
4. Android 不固定在 A，OpenWrt 不固定在 B。所有备份、试启动、故障日志和恢复均由当次实机槽位及镜像身份决定。
5. 每个结论标明“原厂证据／源码覆盖／编译／只读启动／完整系统／长期硬件验收”。不能拿编译或小范围读取替代写入、掉电及休眠恢复验收。

## 1. 先确定实际介质、控制器和原厂行为

连接多台设备时所有 ADB 命令显式指定序列号；不要按网关或第一台设备猜目标。先进入选定设备的 Android shell，再取得 root，保存以下证据：

| 类别 | 必须记录 |
| --- | --- |
| 原厂版本 | 型号、board_id、fingerprint、内核版本、内核配置、原始 DTB/DTBO、相关驱动版本/哈希 |
| 启动链 | 当前 Android 槽、备用槽、两槽 boot 大小/哈希、实际 misc 别名和控制记录格式、两槽 BSP 差异 |
| 存储拓扑 | userdata 别名解析后的节点、sysfs 父盘、SCSI 地址/LUN、UFS controller 路径、driver/compatible |
| 几何 | 父盘及 userdata 的 sysfs size/start、逻辑块大小、物理块大小、GPT 主备头与表、CRC、分区范围 |
| 身份 | 厂商、产品、revision、UFS serial descriptor 是否存在；报告隐藏原始序列号 |
| 加密 | ro.crypto.state/type、实际 /data 挂载源、fstab 的 fileencryption/metadata/keydirectory 设置 |
| 原厂省电 | power/control、clkgate_enable/delay、rpm/spm level、实际可读取的 UFS 错误与链路状态 |

Android root shell 的只读采集示例（`<父盘>`、`<userdata节点>` 和控制器路径必须先人工/程序核实）：

```sh
getprop ro.build.fingerprint
getprop ro.boot.slot_suffix
getprop ro.crypto.state
getprop ro.crypto.type
uname -r
readlink -f /dev/block/by-name/userdata
awk '$2=="/data" {print $1,$3,$4}' /proc/mounts
cat /sys/class/block/<父盘>/queue/logical_block_size
cat /sys/class/block/<父盘>/queue/physical_block_size
cat /sys/class/block/<父盘>/size
cat /sys/class/block/<userdata节点>/start /sys/class/block/<userdata节点>/size
readlink -f /sys/class/block/<父盘>/device
```

by-name 的所在目录也需核实，不能假设所有 Android 都用示例路径。命令缺失时选择同一只读操作的已确认工具，不把读取失败解释成容量为零或“没有分区”。

### 本次实际案例

- U30 Air，`U30Air_SPV1.0.0B04`，原厂内核 `5.4.254-android12-9-gb50b8ab9329f`。
- Samsung KLUGGARHGB-B0E1，UFS 3.1，用户 LUN 为 sda，953.375 GiB；sdb/sdc 各 4 MiB，均不能当成安装空盘。
- compatible 为 `sprd,ufshc`，控制器 `22000000.ufs`，逻辑与物理块均为 4096 字节。
- userdata 为 sda75，FBE＋metadata 加密，Android 实际 /data 来自 dm-39。
- SCSI WWID `eui.53414d53554e4700` 解码只是 SAMSUNG，不能作唯一身份。实际 UFS serial descriptor 可读。
- 与旧 eMMC U30 Air 的电池 DT 对照，50 项一致，但终止充电电流从 300000 变为 420000 µA。说明可复用机型业务，却不能假设所有板级参数完全相同。

## 2. 分清四种单位与设备命名

| 数据 | 单位/含义 |
| --- | --- |
| sysfs 的 start、size | 固定为 512 字节 sector；即使设备是 4Kn 也不变 |
| GPT 头与分区条目的 LBA | 实际设备逻辑块，本次为 4096 字节 |
| ext4/F2FS 的 block | 文件系统自己定义；不得从 UFS 逻辑块推导 |
| 用户界面的 GiB | 字节数除以 2^30 |

统一对上层输出字节或明确的 512-byte sectors，仅在 GPT 编解码边界换算：

```text
factor = logical_block_bytes / 512
start512 = gpt_start_lba * factor
end512_inclusive = (gpt_end_lba + 1) * factor - 1
gpt_start_lba = start512 / factor
gpt_end_lba = (end512_inclusive + 1) / factor - 1
backup_header_lba = disk_size512 / factor - 1
```

整数除法前验证对齐；不允许默默截断。4Kn 上请求 2049 个 512-byte sectors 必须拒绝，不能写成 256 个逻辑块。

本机例子：userdata GPT 起点 1534464 × 4096 = sysfs 起点 12275712 × 512。把它当 512B GPT 会差八倍。

节点分别为 `mmcblk0p75` 和 `sda75`。不要用 `${node%p*}` 或 `${disk}pN` 处理所有介质，也不要假设用户 LUN 总为 sda。从 userdata 的真实 sysfs 父盘建立拓扑，并确认它属于内置 MMC/UFS 控制器；排除 USB/SATA 盘及其同名 userdata 分区。多个内置匹配项不能猜选。

UFS 身份使用实际 serial descriptor，结合 manufacturer 和 LUN 生成带介质域标识的摘要；本次兼容旧事务 CID 字段宽度，使用 SHA256(`ufs:厂商:serial:LUN`) 前 32 个十六进制字符。字段叫 CID 不代表 UFS 有 eMMC CID；状态中另有 STORAGE_KIND。不存在唯一身份时明确拒绝写入，不以通用 WWID、容量或 sda 名字代替。

## 3. GPT 不能只改单个解析器

同时处理电脑与设备两端：

- 按实际逻辑块读取主头 LBA 1 和盘尾备份头，再由头确定表范围。不要固定备份“前 34、后 33 个 512B sectors”。
- 检查两头 CRC、两表 CRC/内容、磁盘 GUID、表条目大小/数量、可用区域和分区不重叠；所有读取/写入范围检查使用一致单位。
- 保留 protective MBR、无关分区条目、唯一 GUID、属性和头所在逻辑块的其他字节。
- 新增、缩容、扩容、重装、续装、卸载归还空间都走同一个单位约定；不要只让首次安装能识别。
- 写入时先完成并校验备份 GPT，再写主 GPT，flush 后回读；失败保留原备份和事务记录。
- Android userdata 内文件系统的空闲空间，不等于 GPT 未分配空间。容量大也不能直接在其尾部覆盖。
- 旧 eMMC 固定裸偏移安装是显式的历史模式，不把其 ROOT_OFFSET 或 GPT 尾预留套到 UFS。

## 4. 内核以本机 DT 和原厂驱动为参照

同一厂商的主线 UFS 驱动并不保证适配同一 DT binding。本例原厂使用 `sprd,ufshc`，而主线另有 `sprd,ums9620-ufs`；不能仅改 compatible 就认为 PHY、reset 和 efuse 已对齐。

本次使用既有 Docker volume 中的 ZTE U30 Air vendor 源码为参照，缓存 HEAD 为 `b50db5b6224c11db42a246e8fcdaad1e1d59f478`。它与实机内核 build ID 不同，必须如实记录；结合实机 DT 与启动结果核对，不宣称二者是完全同版。

移植核对表：

1. clocks/父时钟、resets、regulator、syscon、PHY SRAM 和两个 lane 的 efuse。
2. PHY/DME 初始化与 reset 顺序；efuse provider 未就绪应保留 probe defer。
3. Hibern8 的参考时钟与 hclk 切换、时钟门控延迟及 suspend/resume 顺序。不能靠关闭省电、降速、定时 reset 来掩盖不稳定。
4. UFS variant ops 在各目标内核的 API、const 参数、协商前后参数所有权和 remove/PM 接口。
5. 旧 Android 5.4 的私有 RPMB、HPB、crypto 回调不可直接挪入主线；未实现的能力不置位。能读原始 LUN 不意味着能解密 Android /data。
6. UFS 用户 LUN 需要在挂载根之前可用，选择内建或完整配套的 initramfs 模块；rootfs 里有模块名不代表早期可启动。

**已踩的坑：** lane1 校准值 `0x96910000` 的最高位为 1。有符号 int 同时承载错误码和校准结果会误判；应使用 int 返回码加独立 u32 输出，并检查 nvmem 返回长度与字节序。

本例 6.18 与 7.2 的 `pwr_change_notify` 回调签名不同，按已核验目标内核 API 显式适配；不能只编过其中一条线。新增驱动仅绑定对应 compatible，普通 eMMC 板不应额外探测不存在的 UFS。

## 5. 公共接入面与代码入口

MU300 本次实现的源文件可作为移植参考（尚未提交/发布时，应核对当前工作区，不能假设远端已有）：

| 范围 | MU300 入口 | 迁入 E5 时必须核对 |
| --- | --- | --- |
| 存储拓扑/身份 | `rootfs/overlay/opt/mu300/lib/storage.sh`、`installer/backend/storage.py` | 保留 E5 命名与运行布局，统一来源，拒绝旧/新算法静默回退 |
| GPT | `installer/backend/gpt.py`、`desktop/boot/mu300-gpt` | 对照 E5 的 Python 与设备侧 GPT 工具，统一 512/4K 转换 |
| 早期启动 | `boot/init`、`boot/build-boot-image.py` | E5 的 boot、misc、vendor/NV 发现、根挂载及日志区，不照搬固定偏移 |
| 离线安装 | `desktop/boot/storage.sh`、`part-prepare.sh`、`install-part.sh` | E5 的 `boot/part-prepare.sh`、`boot/install-part.sh` 及各阶段载荷交接 |
| Android 写入 | `desktop/android-write-part.sh`、`android-write-free.sh` | E5 对应写入脚本的父盘、身份、硬范围和 flush/readback |
| 用户态运行 | `android-vendor-start`、`early-recorder`、`mu300-update` | E5 基带/NV 分区映射、启动健康确认和更新入口 |
| 安装器及卸载 | `installer/backend/{adapter,service,install_evidence,uninstall,uninstall_worker,mu300_update}.py` | 本仓库每条更新/续装/卸载路径，不能只替换 GUI 探测 |
| 分发 | `desktop/package.py`、`desktop/boot_image.py`、`installer/build.py`、`installer/package_gui.py` | Python、冻结 EXE、Mac 后端、诊断/卸载 ramdisk 都携带同一库并计入源码指纹 |

特别注意：卸载 worker 需要的存储库必须与其 SHA256SUMS 使用同一归档命名空间。本例为 `openwrt-uninstall/storage.sh`；把库放到 `/etc` 却按工作目录校验，会使实际卸载失败。测试须逐项核验归档清单所指文件确实存在且摘要一致。

调压、LED、充电和基带逻辑保持原有机型隔离。以本机 SML 为例：A/B 全文件哈希相同，与已验证旧固件仅认证区域不同、可执行载荷一致后，才补完整固件哈希识别；不因 SoC 相同给所有 SML 放行。

## 6. 小范围诊断启动与恢复流程

首次用只读 initramfs 确认存储，不直接启动会写 userdata/NV 的整套业务。

1. 从当前 Android 读取并校验当前槽、目标备用槽、两槽 boot、原启动控制；保存电脑端备份。BSP 是否不同先比较，不能擅自覆盖当前 Android 槽。
2. 使用本机 boot 容器/DT 及匹配的 Image、模块。MU300 现有 LK 需要 `upstream/wrap-image.py` 的加载地址包装；换 Image 后必须重新包装，不能复用旧 Image.lk，也不能假设畅行 60 使用相同包装。
3. 通过 ADB/root 写已核验备用 boot，flush 并回读完整摘要，再按本机已有编解码器写一轮试启动记录。只动明确的控制范围，不重写整个 misc。
4. 诊断 initramfs 不挂载 Android、不启基带、不写 NV；报告保存在内存。用独立 USB 地址，DHCP 不下发默认网关/DNS，避免测试电脑改走设备上网。
5. 诊断环境的 BusyBox shell/命令、NCM 和控制台需实测；telnet console 需要挂载 devpts，否则“端口能连但立刻 EOF”是诊断环境问题，不能认定 UFS 坏了。
6. 设置有界回退。本次 probe 在 180 秒尝试强制重启且保留 bootloader 试启动次数回退；这不是任何死锁都能保证恢复，不能代替电脑备份。
7. 先读取型号、版本、LUN、分区和小范围 GPT 摘要；再做间隔读取与有限连续读取。采集省电状态、错误计数/日志，不为通过测试关闭门控。
8. 返回 Android 后核对真实槽位及当前镜像身份，恢复原备用 boot 与**当次备份的原 32 字节控制记录**；回读摘要，再确认 GPT 不变。不要生成一份“默认 A”的记录冒充恢复。
9. 清理且仅清理本次在设备建立的上传目录；保留电脑端镜像、日志和恢复回执。不要因一次诊断顺便清理其他 Agent 的备份或 NV。

另一项失败经验：早期一次 bootloader RAM 引导虽然返回 OK，实机仍进入原 Android；因此返回 OK 不能算新内核启动成功。后续用户已禁止 fastboot，不再使用该方式。验收以真实 uname、驱动绑定、分区和新 init 的证据为准。

## 7. 二进制传输及测试边界

- 本机发现 Android `su -c` 链路可能将原始二进制 LF 变为 CRLF。备份读回电脑须使用已验证的二进制传输实现；本次用设备端 base64 编码、电脑端解码并核对长度/哈希。不要拿损坏的 DTB/GPT 推导硬件结论。
- 初期构造的未做 LK 包装的诊断镜像在刷入前即替换，没有作为有效实机测试；记录应区分“构造过”与“部署过”。
- 避免整盘备份/扫描。按任务读取 BSP、boot、GPT 和必要固件；IMEI/NV、serial 不进公开报告。
- FBE/metadata 加密与 UFS 是独立维度。即使原始 LUN 可读，也不能从 initramfs 读取被加密的安装载荷；需要已完成的两阶段安装/外部传输流程及用户明确清空授权。

验证至少覆盖：

| 层次 | 必测内容 |
| --- | --- |
| 512/4096 离线几何 | 主备 CRC、空闲区增删、缩容布局恢复、不对齐拒绝、损坏与重复请求拒绝、拒绝后原表未变化 |
| 身份和拓扑 | eMMC 不回归、UFS 非 sda 的命名、USB 同名 userdata 排除、重复内置标签拒绝、LUN 边界 |
| 实际设备工具 | 运行发布的 ucode/BusyBox worker，而非仅 Python 镜像；独立解析器检查输出 |
| 更新与卸载 | 两种 Android 槽位、重装/续装、保容量、恢复工作环境、备用 boot 和清单资源完整性 |
| 内核只读启动 | 实际 uname/driver/LUN、几何一致、GPT 摘要一致、空闲后恢复读取、有限连续读及错误日志 |
| 完整系统 | 基带、WAN、热点、USB、充电/OTG、LED、CPU、NV 来源；不能靠临时脚本绕过正式发现路径 |
| 长期硬件 | 正常写入/flush、重启、空闲恢复、实际 suspend/resume；有授权与恢复条件再做掉电场景 |

本次真实结果：两条内核均识别 75 分区；6.18 做 15 次间隔 2 秒的 GPT 读取及 3 次 32 MiB 连续读取，分别摘要一致，未见 UFS I/O 错误。门控开启、10 ms、rpm/spm level 3、power/control=auto；这不证明长期写入或整机 suspend 已通过。

MU300 对应回归入口（WSL 中运行；Windows 可运行环境适用的安装器测试）：

```sh
python3 tests/test_ufs_storage.py
python3 tests/ufs_gpt_runtime.py
python3 -m unittest discover -s installer/tests
python3 -m unittest discover -s installer/tests -p test_uninstall.py
python3 -m unittest discover -s tests -p test_boot_partition_wait.py
python3 -m unittest discover -s tests -p test_update_layouts.py
python3 -m unittest discover -s tests -p test_u30air_integration.py
```

`ufs_gpt_runtime.py` 使用本机已有 OpenWrt Docker 镜像和自有稀疏文件，不访问物理设备；Linux 与 Windows 的跳过项/依赖不同，报告实际运行结果，不能把跳过写成通过。MU300 的 U30 专项报告为 `docs/U30AIR-UFS-ADAPTATION-20261027.zh-CN.md`。

## 8. 畅行 60 的下一次交接清单

以下在 E5 仓库完成，目前均未宣称适配：

- [ ] 设备接入后先记录真实型号、SoC、原厂版本、DT/驱动、UFS 拓扑和加密；“畅行 60”名称不能代替硬件证据。
- [ ] 比较 E5 既有内核是否已经有对应 UFS 控制器和原厂 binding；有可用原厂驱动时先核对其行为，不默认移入 MU300 的主线驱动。
- [ ] 移植统一存储身份与 512/4K GPT 合约。2026-10-27 核对 E5 `installer/backend/gpt.py` 仍固定 512 字节；`boot/part-prepare.sh` 仍限制 mmcblk 节点并读 MMC CID，不能直接在 UFS 上执行分区计划。
- [ ] 扫 E5 安装器、boot、NV 分区发现、更新、卸载、切系统和日志位置的 MMC 假设，保留 E5 自身 NV 保留/同步事务，不能因盘符变化漏掉它们。
- [ ] 用实际新机 DT 建立独立 device profile；板级差异进 profile，纯存储修复进公共层，不能顺手更改现有 E5/T551M/M8 等板的充电、显示、AT 时序。
- [ ] 编译通过 `tools/build-release.py`，仅用登记的已有工作区/准备脚本；不新克隆完整内核、不重复导出 rootfs、不迁 C 盘。
- [ ] 先完成只读诊断启动和恢复回执，再做完整系统及有授权的安装验收。内核、BTF、initramfs/rootfs 模块必须来自同一构建。
- [ ] 构建 Windows/macOS 安装器时将新资源纳入冻结载荷和源码指纹；更新完整包/OTA/Diff Studio 的实际设备校验也要覆盖 UFS。

交付时分别列出源码、构建、部署、用户验收与未测试项，保留明确的下一步，不写“UFS 都一样，直接复制就能用”。
