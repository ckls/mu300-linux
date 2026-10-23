# U30 Air：LP_AP_INTC 实机部署与验证

本文保留先前单模块部署阶段的记录。后续已完成整批运行时、内核及启动优化部署，
当前设备状态见 [完整移植实机报告](U30AIR-FULL-BACKPORT-LIVE-20261023.zh-CN.md)。

2026-10-23，经用户授权，在 USB 连接的 U30 Air 上部署并测试
[liuwang97 的 PR #373](https://github.com/dikeckaan/mu300-linux/pull/373) 本地适配。
本次仅部署 `ums9620_lpintc` 及其开机加载入口，没有部署其他常驻服务、更新内核、
重启设备或生成发布包。

## 设备与部署范围

- 实际机型：`mu300-device` 返回 `u30air`，原厂 DT 的 `charger_policy_service`
  节点存在；SoC compatible 为 `sprd,ums9620`。
- 系统：OpenWrt 25.12.5，`r33051-f5dae5ece4`，ARM64，运行内核 `7.2.8`。
- 管理连接：电脑 `192.168.77.200` 经 USB 连接 `192.168.77.1`；`br-lan` 包含
  `usb0`、`wlan0`。部署使用核对后的 SSH 主机公钥、USB 身份及实际 DT，日志不公开序列号。
- 使用已编译、匹配 7.2.8 的模块，正常 `insmod`，没有强制忽略版本或符号检查。
  模块 SHA-256：`c2dd4e8261e7de8110d7bc6161ce3d58a9555024ec31ea4d8065bb62649a8989`。
- 持久路径：`/lib/modules/7.2.8/ums9620_lpintc.ko`。仅向设备原有
  `/opt/mu300/bin/extra-modules` 插入该模块的加载段，没有用仓库整份脚本覆盖设备版本。
  原脚本备份在 `/etc/mu300/backup/lpintc-20261023/extra-modules.before`，电脑也保留一份。

开机入口已写入并检查 Shell 语法；本次没有重启，因此不将持久化部署写成“已验证重启后加载”。

## USB 延迟对比

电脑使用 Windows .NET ICMP，同一地址、每秒一次，统计真实 RTT；计时分辨率为
1 ms，返回 0 ms 仅代表小于该计时精度，不代表真实传输没有耗时。测试没有触碰电脑网卡或路由。

| 条件 | 收包/发包 | 平均 RTT | 中位 RTT | 最大 RTT |
| --- | --- | --- | --- | --- |
| 原始 CPU0 idle 全部禁用，未加载模块 | 20/20 | 0 ms（精度下限） | 0 ms | 0 ms |
| 暂时允许 CPU0 所有 idle 状态，未加载模块 | 30/30 | 12.37 ms | 0 ms | 67 ms |
| 允许相同 idle 状态，加载模块 | 30/30 | 0.8 ms | 1 ms | 1 ms |
| 恢复原始 CPU0 策略，保留模块 | 20/20 | 0 ms（精度下限） | 0 ms | 0 ms |

共 100 次 ping，无丢包。该短时间 USB 测试支持“模块修复本机允许 cluster-pd 时的
长尾延迟”，不能据此推断功耗、所有负载或所有机型的延迟。加载模块后的独立 5 秒检查，
CPU0 的 `cluster-pd` 使用计数从 1223 增至 1315（增加 92 次），证明没有靠禁用该
idle 状态得到测试结果。

原始 CPU0 三个 idle 状态的 `disable` 均为 1。对比期间临时改为 0，电脑侧 finally
和设备侧超时脚本负责恢复；所有测试结束均恢复为 1。没有改写既有 `mu300-lowlatency`
策略或启动配置。

## 寄存器、加载和副作用检查

首次加载读到原始 INTC0–7 掩码依次为：

```text
f5085c00 2080b9fc 00000000 00000000 00000000 00000000 00000000 00000040
```

与上游记录的 U30 Air TF-A 表一致。模块实际增加 INTC2 `00040000`、INTC4
`00044700`、INTC5 `01fe0000`、INTC6 `02d40018`；刷新周期为 5 秒。
正常卸载后重新加载，八组原始掩码逐一完全一致，验证卸载没有遗留本模块增加的位。

- 模块加载、卸载、重新加载通过；上传与持久文件 SHA-256 一致。
- 测试前后 boot ID 一致，没有重启；无新增 BUG、Oops、WARNING 或 Kernel panic。
- `/etc/config/network`、`wireless`、`unisoc_modem` 的 SHA-256 前后一致。
- LAN 和蜂窝 WAN 均保持 up；没有执行 AT、切 SIM、拨号、短信或充电配置操作。
- 没有写 boot、misc、分区表、userdata、TF、NV 或校准数据。

## 未验证范围

设备当前运行内核实际为 `# CONFIG_SUSPEND is not set`、
`# CONFIG_PM_DEBUG is not set`；`/sys/power/state` 为空，`pm_test` 和 `mem_sleep`
接口不存在。因此没有尝试 `mem` 或假称系统休眠回调已通过；cluster-pd 的 cpuidle
唤醒与整机 suspend 是不同路径。当前本机验证不覆盖 6.18、其他机型、Wi-Fi/PCIe
实际流量下的唤醒、长期稳定性或续航测量。

其他 CPU、modem、系统快照及启动优化尚未部署到这台设备，不将此次结果扩大为整批移植的实机通过。

## 证据与撤回

电脑原始 RTT CSV、设备回读和恢复记录位于忽略目录
`work/pr373-u30air-live-20261023/`，不包含 SSH 密码。

- [部署及 USB A/B 测试日志](../out/build-logs/20261023-051408-pr373-u30air-hardware-61007/command.log)
- [设备能力和卸载掩码复核](../out/build-logs/20261023-051649-pr373-u30air-final-probe-61036/command.log)
- [模块启用时的 cluster-pd 计数及最终状态](../out/build-logs/20261023-051728-pr373-u30air-idle-proof-61053/command.log)

需要撤回时，仅针对该 U30 Air：卸载 `ums9620_lpintc`，恢复上述备份的
`extra-modules` 并移走新增模块文件即可；不需要恢复系统分区或用户数据。恢复脚本前应核对
之后是否又有其他维护任务修改该加载脚本，避免覆盖后续修改。
