# U30 Air 热点启动延迟修复

2026-10-23，完整服务/内核移植部署后，用户反馈热点出现仍较慢。已定位、修复共享
启动脚本，并在同一台 U30 Air / OpenWrt 25.12.5 / 7.2.8 #56 部署验证。

## 已确认原因

启动打点显示 `regdb-load` 从内核 uptime 9.44 秒运行至 29.79 秒，耗时 20.35 秒；
后续模块索引几乎不耗时，WCN 在约 30.4 秒开始加载，热点约 41 秒进入 AP-ENABLED。
原设置为 CN、5 GHz、36 信道、VHT80，不是 DFS CAC 等待。

这台实际运行内核设置为 `# CONFIG_FW_LOADER_USER_HELPER is not set`，
`/sys/class/firmware` 不存在。旧 `regdb-load` 仍为 regulatory.db 及其签名分别等待
sysfs 请求节点，造成一段根本不可能满足的等待。之后正常 `iw reg reload` 成功，
并非数据库或签名损坏。

## 修复范围

- 共享 `rootfs/overlay/opt/mu300/bin/regdb-load` 在 firmware sysfs class 不存在时
  跳过请求节点等待，仍执行原来的 `iw reg reload`，仍由内核验证监管数据库签名。
- 有该 class 的内核保留数据库、签名的原交接及有界等待；reload 失败仍重试并报错。
  没有通过失败切换其他后端、跳过签名、改国家码或放宽信道规则。
- OpenWrt/Ubuntu 使用同一脚本，进入现有共享构建和更新载荷，不做 U30 特例。
- 在 `mu300-hw`、`wifi-start` 增加一次性启动阶段打点，记录监管库、索引、驱动、
  额外模块、配置及 NFC 阶段，便于继续诊断；没有增加常驻轮询。
- 只部署三个脚本；本次没有重新编译内核、GUI、完整 rootfs 或发行包。

## 实机结果

| 时间点 | 修复前 | 修复后 |
| --- | --- | --- |
| board 检查完成 | 9.44 s | 9.36 s |
| 监管库准备阶段完成 | 29.79 s | 9.71 s |
| 该阶段耗时 | **20.35 s** | **0.35 s** |
| WCN 驱动开始加载 | 约 30.4 s | 10.37 s |
| WLAN 驱动就绪 | 35.43 s | 15.39 s |
| 热点 AP-ENABLED / wlan0 桥转发 | 约 **41 s** | 约 **21 s** |

热点提前约 20 秒。阶段耗时来自 `bootmark` 的内核 uptime；AP 的状态由 hostapd
日志和内核 wlan0 forwarding 事件交叉核对，不将 `wifi up` 命令返回当作 AP 已就绪。
这是本次设备的冷启动观测，不作为其他机型或长期统计结果。

用户已用手机确认**能连接热点并上网**。同时复核：

- 国家码仍是 CN，36 信道、80 MHz；监管域正常。
- 蜂窝地址就绪 27.74 秒，WAN 和热点同时 up；原生 modem 的六个命令通道均 open。
- network、wireless、unisoc_modem、unisoc_apn、mu300-charge 以及 Android boot A
  的 SHA-256 均与完整部署前备份一致。
- 无新 BUG、Oops、WARNING 或 Kernel panic；三个部署文件均与当前源码 SHA-256 相符。

## 自动化验证及备份

7 项相关测试全部通过，覆盖无 firmware helper 时零等待、数据库与签名均在 reload
之前完整交接、reload 失败仍有界重试报错、启动顺序、可用热点不重启、不可用热点的
既有单次复核、Unix 换行及既有恢复路径。测试的 sysfs、文件和命令均为私有夹具，
没有用模拟交接冒充实际签名验证或手机联网验证。

- [自动化回归](../out/build-logs/20261023-054646-wifi-regdb-final-regression-62478/command.log)
- [修复前启动打点](../out/build-logs/20261023-054217-wifi-boot-profile-62173/command.log)
- [修复后冷启动](../out/build-logs/20261023-054432-wifi-regdb-fixed-coldboot-62458/command.log)

私有原始观测位于 `work/full-live/wifi-start-baseline.json`、
`work/full-live/wifi-fixed-evidence.json`；部署前脚本和最终校验在 `work/wifi-boot/`。
设备备份目录为 `/mnt/mu300-disk/.mu300/backups/wifi-start-20261023/`。
完整部署清单已同步三个新哈希；原有启动分区和整批运行时备份继续保留。
