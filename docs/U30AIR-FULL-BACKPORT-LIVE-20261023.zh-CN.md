# U30 Air：完整移植部署与实机验证

后续热点启动专项修复已部署：消除监管库加载前约 20 秒的无效等待，热点可用从约
41 秒提前至 21 秒，用户手机已确认连接上网。见 [Wi-Fi 启动报告](U30AIR-WIFI-BOOT-20261023.zh-CN.md)。

2026-10-23，用户明确要求把整批改动部署到连接的 U30 Air，包含之前移植的
启动、常驻服务及事件驱动优化，不限于 PR #373。本文记录完整部署后的状态；
此前只部署 LP_AP_INTC 的记录见 [单模块报告](U30AIR-LPINTC-LIVE-20261023.zh-CN.md)。

## 部署完成范围

实际 DT 的 `charger_policy_service` 和 `mu300-device` 均确认 U30 Air；维护连接
绑定核对后的 SSH 主机公钥及 USB 身份，不依靠管理 IP 猜设备。Android 为 A，
OpenWrt 为 B，独立内置 `mmcblk0p76` 上的 OpenWrt 25.12.5。没有格式化、缩扩容
或变更安装方式。

- 已部署并逐一 SHA-256 核对 **207 份运行时文件**，包含本仓库共享脚本/库、
  OpenWrt 服务与网络入口、LuCI 代码、RPC/ACL、ucode 模块、静态 AT bridge 和按键 helper。
- 已通过原 `upstream/make-bundle.sh` 使用已核验产物生成部署用内核包，并通过当前
  `mu300-update boot` 安装 **7.2.8 #56**、**202 个模块**及当前 `boot/init` 的
  generic ramdisk。使用本机原有 boot header、AVB 尾及设备 ramdisk，启动分区回读通过。
- 启动优化已实际运行：PCIe 初次探测等待、模块预读、随机池初始化、UART 输出级别、
  USB 固定等待删除、eMMC 就绪探测、Wi-Fi 顺序和 SIPC/数据就绪检查。
- `mu300-modemd`、`mu300-atd-io`、`mu300-sysd`、原生快照/网速、SMS/data/NDP
  事件监听及服务小核调度均已运行；OpenWrt 的旧 buttons init 和 post 内旧 thermalguard
  入口已移除。原 CLI 与显式平台入口保留，没有失败时自动切旧后端。
- PR #373 模块保留并在本次重启后加载。原有 CPU0 lowlatency 策略保留，没有因部署而
  擅自改变用户选择的 idle、频率、充电或无线电策略。

本次没有构建 GUI、完整 rootfs 或发行压缩包；生成的内核部署包仅用于实机维护。

## 旧版本缺失依赖的处理

设备未部署用户前一天的更新。初次按当前 Git 差异安装的 39 份文件没有覆盖旧设备缺失的
`sms-pool.sh`，导致 AT 服务在入口加载时明确失败，蜂窝 WAN 未起来。
该次启动属于失败记录，不计作验证通过，也没有临时启用旧 broker。

随后对当前仓库完整运行时做核对：补齐另外 9 份缺失/过期文件，涉及 SMS pool/CMT
spool、dual-radio、短信/toolkit/VPN、SMS forwarding、相应 VPN init 和 settings 页面；
207 份文件最终全部与本地源一致。该问题来自旧设备的部署基线，当前 rootfs 构建流程
本身会携带完整共享库。补齐后重新冷启动，所有八路物理 AT/URC 描述符正常打开。

## 启动实测

先在原版本执行一次重启建立基线，再部署后复核。表内时间来自内核 uptime 和实际
`bootmark`，不是电脑侧进度估计；SIM、网络、APN 和充电配置保持一致。

| 时间点 | 原系统 | 完整部署后的最终冷启动 |
| --- | --- | --- |
| initramfs devfs 就绪 | 2.24 s | 0.36 s |
| 模块加载完成 | 3.66 s，26 个成功、0 失败 | 0.61 s，26 个成功、0 失败 |
| 早期 USB DHCP 就绪 | 5.14 s | 1.17 s |
| switch_root | **5.17 s** | **1.20 s** |
| Android vendor 服务入口 | 13.64 s | 8.02 s |
| AT 服务入口 | 15.95 s | 10.01 s |
| RIL 握手完成 | 18.72 s | 12.54 s |
| 蜂窝注册完成 | 33.76 s | 26.69 s |
| PDP 激活 | 37.28 s | 27.57 s |
| 蜂窝地址就绪 | **37.33 s** | **27.69 s** |

switch_root 提前 3.97 秒；蜂窝地址提前 9.64 秒，约 25.8%。另一轮补齐后的启动
记录为地址 28.08 秒，也已正常联网；其电脑侧观察器因 SSH 恢复早于 configfs 身份节点
发布而退出，未把那轮 SSH 可用时刻作为有效测速。观察器已修正为等待同一路径身份就绪，
最终冷启动重新通过，没有降低设备身份校验条件。

电脑从发出 reboot 到 SSH 可用为 42.33 → 35.14 秒，包含 bootloader 和电脑网络
恢复时间，与上述内核时间起点不同。这里只报告一次原版本基线和完成后的两轮启动，
不声称多次统计结果或所有网络环境都能达到相同收益；蜂窝注册仍受运营商影响。

## 功能、恢复与副作用检查

| 项目 | 实机结果 |
| --- | --- |
| 版本一致性 | 207 份运行时文件、202 个模块 SHA-256 全部匹配；实际运行新 #56 内核。 |
| AT 所有权 | NR1/2/4/5/6/7 六个命令通道和 NR0/3 两个 URC 通道全为 open；扫描 `/proc/*/fd` 确认八路均仅由同一个 C bridge 持有。 |
| 实时读取及兼容 CLI | 原生实时信号 RPC 成功；原 `mu300-at` 在 daemon-only 模式下读取 CSQ 成功，没有直接打开 tty 作为测试捷径。 |
| daemon 恢复 | 仅向 ucode modem daemon 发送 TERM，正常由 procd 拉起；新 PID 接回原 bridge，bridge PID/物理通道所有者不变，WAN 保持 up，CLI 再读成功。没有重启完整 AT 服务或重置射频。 |
| 看板和流量 | 原生 sysinfo/status/cells、rates、sms_head 可用；WAN、热点及 modem alive 均正常。15 次设备端 sysinfo 调用平均 38.75 ms、最大 66.66 ms（包含启动 ubus 客户端）。未采集同条件旧 RPC 耗时，因此不声称本机页面 CPU 的具体提速倍数。 |
| 浏览器接入 | 用独立测试登录会话走 HTTP `/ubus`，实际调用 status、rates、sms_head 全部成功；HTTP 返回的 common.js 与本地源 SHA-256 相同，测试会话已清理。 |
| 小核调度 | 重启后 procd services 的有效 cpuset 为 `0-3`，读取的保存模式为 little；没有 CPU 下线或 DVFS 改写。 |
| 事件监听 | SMS 的两槽监听、data 的 ubus listener、NDP 的 ip monitor 均运行，旧 shell AT owner 和旧 thermalguard 不再运行。 |
| 联网 | LAN/蜂窝 WAN 均 up，热点实际处于 up；指定蜂窝接口访问 generate_204 得到 HTTP 204。 |
| 内核状态 | 最终冷启动及恢复测试无新 BUG、Oops、WARNING 或 Kernel panic。 |
| 配置与 Android 保护 | Android `boot_a` 全分区及 network/wireless/unisoc_modem/unisoc_apn/mu300-charge 的 SHA-256 前后一致。 |

20 秒无页面轮询的 CPU 采样中，全部 CPU 的非 idle/iowait 时间合计 149 ticks，
`CLK_TCK=100`，约为单核 7.45%。这是**包含内核、网络栈和全部进程**的整机统计，
不是 mu300 常驻服务单独 CPU，也没有同条件原版本 CPU 基线；不能与上游 0.3%
用户态数字直接比较。

## 未验证范围

- 用户使用物联卡，无法进行短信收发实测；这里只验证接收服务、事件监听及状态接口。
  不注入模拟短信到真实消息池，不冒充真实收信通过。
- 没有实际切换 SIM、重置蜂窝、拨打电话、改变充电策略，或操作 NV/校准分区。
- 没有人工实体按键、NFC 读写或长时间 Wi-Fi 客户端流量测试；不以 daemon 存活替代这些实测。
- 系统 suspend/恢复、长期待机功耗/续航、其他机型和 6.18 仍未实机验证。
  LP_AP_INTC 的本机 USB/cluster-idle 测试仍见单模块报告。

## 备份与证据

设备侧原文件、原模块、配置及启动元数据归档、boot B 原镜像位于：

```text
/mnt/mu300-disk/.mu300/backups/full-native-20261023/
```

电脑双份校验备份、完整文件清单及私有原始观测保存在
`work/full-live/`；归档可能含设备配置，应作为备份保管，不上传公共仓库。
配置正文、短信正文、SSH 密码及测试会话 token 未写入公开报告。
当前 `mu300-update rollback-boot` 的 prev.body/vbmeta/footer 也保留；需要回滚整批时必须
同时恢复旧运行时和旧配套模块，不能仅退 boot 而混用不同版本依赖。

| 阶段 | 日志 |
| --- | --- |
| 原构建器生成内核部署包 | [kernel bundle](../out/build-logs/20261023-052152-full-u30air-kernel-bundle-61089/command.log) |
| 双端备份、初始暂存与导入检查 | [backup/stage](../out/build-logs/20261023-052245-full-u30air-backup-stage-61969/command.log) |
| 更新前冷启动基线 | [baseline](../out/build-logs/20261023-052445-full-u30air-baseline-boot-61990/command.log) |
| 内核、模块、启动分区和运行时部署 | [deploy](../out/build-logs/20261023-052555-full-u30air-deploy-62013/command.log) |
| 完整依赖核对和补齐 | [runtime reconciliation](../out/build-logs/20261023-052955-full-u30air-runtime-complete-62060/command.log) |
| 功能、AT 描述符、daemon 恢复、CPU 及联网测试 | [hardware validation](../out/build-logs/20261023-053307-full-u30air-hardware-validation-62095/command.log) |
| 最终完整冷启动 | [final cold boot](../out/build-logs/20261023-053350-full-u30air-final-coldboot-62117/command.log) |
| 最终浏览器 HTTP API 和重启后状态复核 | [browser API](../out/build-logs/20261023-053536-full-u30air-browser-api-final-62157/command.log) |

保留失败记录：初次差异部署缺短信库的蜂窝启动失败、观察器遇到暂未发布的 configfs
身份路径、以及 HTTP 测试会话销毁权限与测试脚本预期不同。前两者分别通过补齐完整依赖、
等待原身份路径解决；会话清理由已核对的 SSH 维护连接执行，仅清理测试自身的会话。
修正后重新执行对应验证，不把失败日志隐藏或解释为已经通过。
