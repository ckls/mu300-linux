# U30 Air UFS 版本：存储适配与验证记录

后续机型使用 [通用 UFS 适配指南](UFS-PORTING.zh-CN.md)，其中包含单位合约、
踩坑、恢复流程及 E5 仓库畅行 60 的待办。本文仅记录本台实际证据。

已接入两条主线内核的 UFS 驱动，并将安装、启动、基带分区映射、更新和卸载接到统一存储描述。

**已在实机分别启动 7.2.8 和 6.18.54 的诊断 initramfs，验证 UFS 只读访问；尚未完成完整 OpenWrt 安装验收。** 两次测试通过 Android ADB/root 临时写入备用 boot B 和 32 字节启动控制，当前 Android A 的 boot 未改。测试结束恢复原 boot B 和原启动控制并校验；未改 GPT、未格式化 userdata、未写 NV。后续禁止使用 fastboot。已有 LAN 地址修复保持原样。

## 实机证据

| 项目 | 本机值 |
| --- | --- |
| Android 固件 | `U30Air_SPV1.0.0B04`，fingerprint `ZTE/U30Air/U30Air:13/TP1A.220624.014/20241014.163923:user/release-keys` |
| 内核 | `5.4.254-android12-9-gb50b8ab9329f` |
| 平台 | UMS9620；当前 Android A 槽 |
| 存储 | Samsung `KLUGGARHGB-B0E1`，revision `0901`，UFS 3.1 |
| 用户 LUN | `/dev/block/sda`，1,023,678,611,456 字节，953.375 GiB |
| 其他 LUN | sdb、sdc 各 4 MiB，不能视作普通空闲盘或安装目标 |
| 控制器 | `22000000.ufs`，设备树 `sprd,ufshc`，模块 `ufs_sprd_qogirn6pro` |
| 逻辑/物理块 | 均为 4096 字节 |
| userdata | `sda75`，GPT LBA 1,534,464～249,921,023，1,017,391,349,760 字节 |
| userdata 加密 | `ro.crypto.state=encrypted`、`ro.crypto.type=file`；fstab 有 fileencryption/keydirectory，实际 `/data` 来自 dm-39 |
| 已有 OP 分区 | 未发现 `mu300root` |
| 原厂省电 | `power/control=auto`，时钟门控开启、延迟 10 ms，rpm/spm level 3；未改动 |

主、备 GPT 头 CRC、表 CRC 和两份分区条目一致性均已在电脑端验证。固件原始 DTB、内核配置、GPT 小范围快照及摘要在 `work/u30air-ufs-20261027/`。未读取整盘、userdata 内容或 NV；另保存两槽 boot 与启动控制以恢复临时内核测试。

## 首要问题：不能仅替换 mmcblk0 为 sda

### 与既有 U30 Air 的非存储部分对照

本机仍是 UMS9620/T760，Marlin3＋SC2355 PCIe 无线、UMP9620 PMIC/FGU/Type-C、I2C6 的 BQ2560x 兼容充电器、ZTE LDO 灯控以及 cpufreq-v2 均对应现有 U30 Air 适配路径，应复用这些功能而非重新建立一套机型业务。

与此前 eMMC U30 Air 保存的 `work/u30air-charge-early-full-20261022/battery-dt.json` 比较：50 项值一致；确认一项实际参数差异：`battery/charge-term-current-microamp` 旧机为 300000，本机为 420000。旧采集中的若干字符串以 Python bytes 表示，与当前 DTS 的纯文本显示差异不算硬件差异；`name` 为旧采集的节点名称，不是当前 FDT 缺失硬件。

因此结论是“主要适配存储，复用 U30 Air 业务并读取本机参数”，而非“除 UFS 外所有参数逐字相同”。当前没有完整的旧 eMMC 原机 FDT 可逐节点对照，尚不能保证所有 GPIO、射频固件和板级参数完全一致。

另只读提取本机 SML A：完整 SHA-256 为 `6e3b9234525ace117a503925c8f8db0ed05e1679bd773d4731b56334140f5a2f`，与现有完整镜像允许列表不同；但原已验证 U30 Air 的可执行载荷范围 `[0x200,0x23150)` 哈希仍为 `119f874110ce04f9623cda30b85bae35b2ad7da494a1a26c1f7553f9f64bb1fd`，完全一致。两槽 SML 完整文件相同；与原已验证镜像相比，仅签名/认证区域不同，可执行载荷一致。已将本机完整哈希加入 U30 Air 调压识别，不按 SoC 泛化放行。实际调压效果尚未做整机验证。

这台机器 GPT 的 LBA 单位是 **4096 字节**，但 Linux sysfs 的 `start`、`size` 仍以 **512 字节**为单位。例如 userdata 的 GPT 起始 LBA 是 1,534,464，sysfs start 是 12,275,712；它们描述相同的字节偏移。

修改前两条主线发布内核配置未接入这颗 QogirN6Pro UFS 控制器；本次已补入配置与专用驱动。`boot/module-order*.txt` 中存在 UFS 模块名称是旧 vendor 内核路径，不能证明 6.18/7.2 内核已经支持 UFS。

另外，本机 SCSI WWID 是 `eui.53414d53554e4700`，内容只是厂商字符串，**不能当作唯一身份**。实际 UFS string descriptor 的 serial_number 可读；应使用这个序列号，结合 LUN、控制器归属、容量和分区几何验证。报告不公开原始序列号。

## 已实现的公共路径

### 1. 内核驱动与原机设备树

- 为两条发布内核接入 UFS core、platform 及 UMS9620/QogirN6Pro host/PHY；保持现有 eMMC 路径。
- 以本机 DTB 的 clocks、resets、regulator、PHY SRAM、两个 efuse 校准项为准。不能将另一款 SoC 的 `ufs-sprd` 直接绑定到同名 compatible。
- 本机已存在 `mu300-kernel` Docker volume 中的 U30 Air vendor 源码可作为移植输入，无需复制整棵源码或重新下载内核。缓存源码 HEAD `b50db5b6224c11db42a246e8fcdaad1e1d59f478`，其中 `ufs-sprd-qogirn6pro.c` 1240 行；它与本机 kernel build ID 不同，不能声称已核对为完全相同的原厂版本。
- 移植需核对新旧 UFS variant ops，特别是原厂的 PHY initialization、hibern8、reset、efuse 和 suspend/resume；不以关闭休眠或降速替代适配。

### 2. 统一存储描述与扇区单位

- 从 userdata 的实际父设备解析系统盘，确认其为本机控制器 LUN；不假设 UFS 永远是 sda，也不扫描 USB 硬盘后随意接受同名分区。
- 存储描述包含介质类型、父盘、分区号、逻辑块大小、容量和设备身份。eMMC 保留 CID；UFS 使用可验证的 serial descriptor。
- 容量/偏移计算使用字节或明确的 512-byte sector 单位；GPT 层单独按设备逻辑块大小转换。主备 GPT 读取、CRC、表写入、回读都使用同一逻辑块大小。
- 分区命名不能再使用 `${node%p*}`、`${disk}pN`：分别支持 `mmcblk0p75` 与 `sda75`。

### 3. 启动、基带、安装和更新一起接通

| 范围 | 已修改的入口 |
| --- | --- |
| 启动槽位、日志落盘 | `boot/init` 的 misc/boot 搜索；`early-recorder` |
| 内部根分区 | `desktop/boot/storage.sh`、`part-prepare.sh`、`install-part.sh`；旧 free-region 模式不可对 UFS 沿用固定偏移 |
| 基带分区映射 | `android-vendor-start` 和 `boot/init` 的 mmcblk0 PARTNAME 枚举 |
| 安装器探测、备份、分区 | `desktop/installer.py`、`installer/backend/adapter.py`、`gpt.py` |
| Android 分区写入 | `desktop/android-write-part.sh`、`android-write-free.sh` 的 CID、父盘与分区节点验证 |
| 更新与卸载 | `service.py`、`mu300_update.py`、`desktop/update_control.py`、卸载事务/worker 的身份和几何验证 |
| 系统切换/OTA | 检查所有 misc、boot、根设备正则和持久记录，不将 sda 分区拒为非法设备 |

基带、LED、充电、CPU 等仍属于 U30 Air。存储介质应作为独立维度，不凭型号建立一套重复业务实现。

### 4. 验证与首次安装边界

已完成下述源码及只读实机验证。完整 OpenWrt、实际分区写入及升级卸载仍需单独验收；本次未生成正式发布包，旧发布包不会因源码改变而自动支持 UFS。

本机容量基本已分配给加密 userdata，没有可直接容纳 OpenWrt 的大块 GPT 空闲区。若使用当前“加密 userdata 清空后缩容”的安装方案，需要另行取得用户对清空 Android 数据及分配大小的明确授权；本次没有此授权，也没有执行。不要尝试从 initramfs 挂载加密 userdata 获取安装载荷。

## 驱动实现与实际结果

- 新驱动在 `upstream/port/drivers/ufs/host/ufs-sprd-qogirn6pro.[ch]`，由现有 port 安装入口加入 Kconfig/Makefile；两条内核都内建 UFS core/platform 和本驱动。
- 保留本机原厂 PHY/DME 初始化、双 lane efuse、Hibern8 时钟/参考时钟切换和 suspend/resume 顺序。5.4 的私有 RPMB/crypto 回调没有冒充主线 API；不宣称可解密 Android userdata。
- 适配中确认 efuse lane1 为 `0x96910000`，最高位为 1。原逻辑若混用有符号错误码与校准值会误判；现使用返回码与 `u32` 输出分离。实机两条内核均正确读取两条 lane 的校准值。
- 7.2.8 在约 0.87 秒、6.18.54 在约 0.94 秒创建用户 LUN 及全部 75 个分区。GPT 前 32 KiB 的摘要与 Android 下采集结果相同。
- 6.18.54 做了 15 次间隔 2 秒的 GPT 读取，以及 3 次连续 32 MiB 读取；摘要各自一致，未见 UFS I/O 错误。它们只是小范围只读测试，不能证明长期写入或断电可靠性。
- 实机保持 `power/control=auto`、`clkgate_enable=1`、门控延迟 10 ms、rpm/spm level 3。没有以禁用休眠或降速替代适配；未执行整机 suspend 验收。
- 普通 eMMC 机型的原始偏移 legacy root 路径保留，仅在确认系统盘为 mmcblk0 时使用，不对 UFS 硬套旧偏移。

## 回归证据

- Windows 安装器测试：352 项运行，环境适用项通过，74 项按条件跳过。
- Linux 卸载 worker 回归：22 项全部通过，覆盖实际 BusyBox worker 的重置、空闲区安装撤销、中断续接及 Android A/B 两种槽位。
- UFS 专项覆盖 512/4096 字节 GPT 主备校验、空闲区增删、userdata 缩容后的布局还原、设备身份、外接 USB 同名分区排除和不对齐请求拒绝。
- 实际运行发布的 ucode GPT 工具，在自有稀疏测试文件验证 list/plan/carve/uuid/resize/add、重复请求拒绝；独立 Python 编解码器检查 CRC 与边界。没有对设备运行这些写分区测试。
- 卸载 initramfs 中统一存储库位于 `openwrt-uninstall/storage.sh`，纳入同目录 SHA256SUMS，回归检查归档内每项均可按清单定位和核验。
- 完整 Image 和模块两套均构建通过；日志分别在 `out/build-logs/20261027-110214-ufs-kernel-72-5169/`、`out/build-logs/20261027-110548-ufs-kernel-618-5341/`。没有复制新的内核源码/对象树。

## 尚未完成

1. 完整 OpenWrt 下的蜂窝、无线、灯控、充电、CPU 调频调压等使用原有 U30 Air 业务，但本台 UFS 机尚未逐项整机验收。
2. 本机原 userdata 加密且占用剩余大部分 GPT 空间；继续内置安装需要明确的清空授权和分配大小。本次未获授权，故未分区或格式化。
3. 正式安装器及固件发布包尚未重新编译组装；两套内核产物已经更新，不能混用旧模块或旧安装器发布。
4. 本机 DT 还声明了未能发现卡的 `22200000.sdio` 非可移除 MMC 控制器，诊断内核有一次初始化失败日志。它不影响本轮 UFS 读取；尚无依据修改此节点或把它当成反复掉盘。

以上“未完成”不能写成已通过硬件验证。后续适配 UFS 机型应沿用统一存储层，板级 compatible、PHY、efuse 与充电参数仍须核对该机原厂证据。

## 本次执行过程与证据位置

时间为 2026-10-27 UTC+8；原始记录在本仓库 `work/u30air-ufs-20261027/`。

| 阶段 | 操作、结论与证据 |
| --- | --- |
| 原厂只读调查 | `summary.json`、`inventory-live.json`、`stock-live.dtb/dts`、`stock.config`、`ufs-sysfs.txt`、`ufs-policy.json`。summary 的 hardware_mutations=false 是这个初始阶段的快照，不是后续诊断启动从未写 boot 的声明 |
| GPT 核验 | `gpt-first-32k.bin`、`gpt-last-24k.bin`、`gpt-layout.json` 和 `gpt-live-shared-proof.json`；base64 传输纠正 su 通道对二进制的 CRLF 改写风险后，验证两头两表及 CRC |
| 非存储复用判断 | `nonstorage-comparison.json`、`sml-comparison.json`。没有将“同是 U30 Air”当作充电参数和 SML 一定相同的证据 |
| 驱动与双内核构建 | 保留 vendor PHY/efuse/Hibern8，修正校准值与错误码混用；分别解决 6.18/7.2 API 差异，构建完整 Image 与模块，日志路径见上 |
| 早期引导失败经验 | 一次 bootloader RAM 引导返回 OK，实际仍是原 Android，未计为新内核验证；后续按用户要求禁用 fastboot。最终使用 ADB/root 备用槽试启动。未包装 LK 的早期构造镜像没有刷入 |
| 7.2.8 试启动 | 19:22:37 经 ADB/root 写备用 B 和当次试启动记录，`probe-live-report.txt` 记录实际内核及 75 分区；19:27:21 恢复原 boot B 与原控制记录，`trial-state.json` 状态 restored |
| 诊断通道完善 | 第一版 telnet 连接 EOF 是缺少 devpts；第二版挂载 devpts，控制台可执行只读命令。关闭连接前未确认命令执行，也不能当作已重启，最终以实机重枚举和 Android 版本核验 |
| 6.18.54 试启动 | 19:29:20 经 ADB/root 开始，`probe-618-report.txt`、`probe-618-repeated.txt`、`probe-618-extended.txt` 保存只读结果；19:32:40 完成还原，`trial-state-618.json` 状态 restored |
| 最终收尾 | 两槽恢复后 SHA256 均为 `452a2bc393fc1f538fe462639780b4f259df8efd2f80da998d3616ec0088779b`；原启动控制按当次原始 32 字节回读验证，GPT 前 32 KiB 与初始快照一致。删除本次设备端上传目录，保留电脑端备份，`inventory-final.json` 用最终公共库在 Android 再次验证拓扑 |

不是整盘备份，也未碰 NV/IMEI 或 Android userdata 数据。内核读盘成功后仍保留“完整 OpenWrt 未安装”的边界；后续安装需独立处理加密 data 授权与空间选择。

离线运行记录：`installer-tests-final.log`（352 项运行、74 跳过）、`uninstall-linux-final.log`（22 项通过），以及源码中的 `tests/test_ufs_storage.py`、`tests/ufs_gpt_runtime.py`。后者对 512/4096 两类稀疏文件实际运行 ucode GPT 工具，不向本机块设备写入。
