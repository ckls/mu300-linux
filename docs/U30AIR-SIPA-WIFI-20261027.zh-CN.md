# U30 Air UFS：SIPA 线程修复与原厂无线对照

## 结论

2026-10-27 在已连接的 U30 Air UFS 上，修复并部署了 SIPA 两个线程
长期停留在创建阶段 D 状态的问题。无线初始化的两个拒绝回包经同机原厂
Android 实测也存在，不能认定为本次 OpenWrt 移植引入的驱动缺陷。
本轮未更换无线固件、修改 RF INI、校准数据、功率表、休眠策略或蜂窝 AT 顺序。

## SIPA 修复

涉及 `upstream/modules/sprd_modem/sipa_v3/sipa_skb_send.c` 和
`sipa_skb_recv.c`，6.18/7.2 的 MU300、F50、V50、U30 Air 共用。

旧实现通过 `kthread_create()` 创建 sender/receiver 线程，只有首次资源恢复
才调用 `wake_up_process()`。未建立蜂窝数据连接时，两个线程长期处于尚未执行
工作函数的 D 状态，引发 hung-task 告警并抬高负载，而非阻塞在 UFS I/O。

改为创建时运行工作函数，在可中断等待队列中等待原有首次 resume 事件：

- 首次 resume 前通过 `init_flag` 短路条件，禁止访问 FIFO/MMIO，包括队列已有
  工作、意外唤醒和信号中断的情况；不提前开启 SIPA 硬件或改变资源握手顺序。
- resume 清除初始标记并唤醒原有队列，后续保持既有发送回收和收包补充路径。
- 等待条件包含停止请求，信号中断不误进入硬件处理。
- 线程注册 devm 停止动作，释放结构前停止；同时修正 sender 的 devm 分配对象
  使用裸 `kfree()` 的错误路径，初始化回调前先初始化等待队列。
- receiver 数组初始化失败时直接返回错误，避免继续发布不完整对象。

`tests/test_sipa_worker_lifecycle.py` 抽取真实工作函数，用 pthread 等待队列执行
首次 resume 前等待、已有待办、意外唤醒、信号中断、resume 后工作以及两阶段
停止测试。与已有 SIPA TX 重试测试合计 3 项通过；这不等于已测试欠费卡的数据传输。

## 无线：同机原厂证据纠正了初步判断

从本机 UFS `super` 的逻辑分区只读提取原厂模块与固件，没有安装整套 Android
根镜像，也未从相似型号替换输入：

| 输入 | SHA-256 |
| --- | --- |
| 本机 vendor_dlkm_a / sprd_wlan_combo.ko | `c55c6fd33210741371ca389aa850dd13d6c28293c5dd78c9ac8a667c64deef61` |
| 本机 odm_a / firmware/wcnmodem.bin | `a3210c08f0702d7bfcfff21f3d09226b38412de79782c1eac9443615ace47e70` |
| 本机 odm_a / firmware/wifi_board_config.ini | `47a4e23d96e7334750fdb52b0f283f8f64949605b8ba9df2d835f00ea1f07a1d` |

后两项与 OpenWrt 当前使用的文件逐字节一致。原厂模块反汇编确认：

- `cmdevt_download_ini +0x1e844` 同样发送 section + 三个保留字节、原始数据、CRC；
  第三段 RF 长度同为 129 字节。
- `sc2355_set_power_backoff +0x1f288` 同样向命令 5 发送 18 字节，子类型 `0x11`。
- `sc2355_fcc_fresh_bo +0x345dc` 同样使用上述功率回退路径。

临时启动本机原厂 Android A 槽，读取已有启动日志后恢复原始启动控制信息、
正常重启回 OpenWrt B 槽。Android fingerprint 为
`ZTE/U30Air/U30Air:13/TP1A.220624.014/20241014.163923:user/release-keys`，
WCN 版本 `MARLIN3_20A_RLS2_W24.29.5 / 07-19-2024 09:52:19`。
没有修改原厂 Wi-Fi 配置或开启测试热点。

原厂内核日志原样包含：

- 8.066602 秒：`CMD_DOWNLOAD_INI / SPRD_CMD_STATUS_UNKNOWN_ERROR`。
- 8.113508 秒：`CMD_POWER_SAVE / SPRD_CMD_STATUS_ARG_ERROR`。

OpenWrt 临时命令跟踪把第二项关联到 `sc2355_set_power_backoff`，并非普通
`sc2355_power_save` 休眠开关。所有临时探针及独占 tracing instance 已移除。

因此，已排除“OpenWrt 引入新的报文格式错误”这一初步疑点；原厂固件本身仍会
拒绝这些扩展配置，未证明它们没有性能影响，也没有使固件接受它们的已验证方案。
不把删日志、跳过 RF 配置、换功率表或禁用省电冒充修复。

## 构建与部署

通过 `tools/build-release.py run` 复用已有构建 volume，6.18.54、7.2.8 的
sprd_modem 配套模块均编译通过。7.2.8 实机与构建 vmlinux BTF SHA-256 同为
`be01d4db0f8c9daff839127cb2a10f5f4b622248a80acca1845ae6df3fa31371`。

实机只替换根文件系统及当前 Linux B 槽 initramfs 中的 `sipa-core.ko`。
启动镜像只追加该模块覆盖段；逐项验证 kernel、其余 CPIO 文件、启动参数和
48 MiB 之后的持久日志区保持，Android boot A 的完整哈希未变。
刷入后回读校验成功，未使用 fastboot、未修改 NV 或重新安装系统。

重启后两个线程均为 S 状态，栈已进入各自工作函数的等待点；此前约 3 的 load
降至约 0.6（短窗口，不能视为续航测量）。AT broker/URC、USB 管理网络与
5 GHz 热点正常，ext4 错误数仍为 0。卡欠费，未测试蜂窝吞吐和资源活动状态。
恢复 OpenWrt 后再次核对模块 SHA-256 为
`a3c160a104eb710949912b1abeb1f3152097ede3cf3dea5e92239c4f6b60533e`。

源码、两条内核的模块缓存及本机已更新，既有发布 ZIP 尚未重新打包。
本机证据、原始启动镜像和部署收据保存在
`work/u30air-ufs-20261027/driver-fixes/`，含敏感设备日志，不应整体公开。
