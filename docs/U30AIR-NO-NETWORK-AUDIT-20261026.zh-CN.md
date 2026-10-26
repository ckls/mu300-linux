# U30 Air 新版无网络：SIM 上电与存在性判断

2026-10-26。反馈为“老版本正常，新版本无网络”，尚无准确新旧包版本、故障日志或故障设备。没有据此回滚整批更新，没有连接/改写实机、刷写内核或操作 NV。

## 已确认的代码缺陷

U30 Air 现由公共 `mu300-dual-radio` 初始化双卡。旧代码先读两张卡的 `CPIN?`，收到 `+CME ERROR: 10` 就认为不存在，后续跳过该卡的 `SFUN=2`、模式初始化及 `SFUN=4`。两卡均被判为空时，还会发布 `mu300-dual-radio-ready`。

这与仓库既有 U30 实测证据冲突：物理卡插着、SIM 电源关闭时，也可能收到 CME 10。仅凭未上电前的 CPIN，不能证明这个位置没卡。

依据为 `f0b5ad43^:rootfs/overlay/opt/mu300/bin/mu300-sim-u30` 的 `card()` / `preflight()`：

- 历史记录明确写明，第二位置在每次启动时可能因 SIM 未上电而返回 no-sim。
- 旧 U30 的存在性预检先发目标卡 `SFUN=2`，再确认 CPIN；该操作只给 SIM 上电，不启动 RF。
- 这里引用的是已有实机测量记录，并不是本次重新取得的 Android RIL 抓取。

U30 于 `f0b5ad43`（2026-10-23）切换为共享双卡入口后，会经过这一原本用于其他机型的判断。相关当时验证报告位于 `docs/U30AIR-MANUAL-DUAL-SIM-20261023.zh-CN.md`，记录的样机基带为 `5G_MODEM_V2_23A_W25.03.2`，日期 `01-14-2025 10:14:02`，当时两卡均已返回 READY。这不能覆盖所有设备的 SIM 初始供电状态。

## 本次修正

只在以下条件全部满足时处理该歧义：

- 识别为 `u30air`；
- 本次启动尚未完成双卡初始化；
- CPIN 明确返回 CME 10（或同义文本）；
- CFUN 回读为 0 或 2，不能以超时/空值猜测电源状态。

这时先执行原有 SIM 上电步骤 `SFUN=2`，再确认 CPIN。若卡仍明确不存在，继续跳过它的模式和 RF 启动；若 busy、超时或上电失败，结束本轮，不伪造初始化成功。交由原有拨号重试处理，不增加轮询或复位机制。

本次已提前完成的 `SFUN=2` 不在后续冷初始化中重复发送。正常 CPIN 可读的路径保持原有上电/模式/选卡/回放/射频顺序；不改变默认数据卡和用户保存的射频开关。已初始化的设备不进入此预检，F50/V50 不使用 U30 专有补正。

同时将 CME 10 改为整行匹配，避免把 `+CME ERROR: 100` 等其他错误当成物理无卡。该错误分类修正适用于公共双卡脚本。

## 与 E5 反馈的关系

E5 使用 ModemManager；MU300 维护树使用自己的 AT broker 和 `mu300cell`，不能把 E5 的“MM 模组对象失效”直接解释为 U30 的根因。

E5 的 CPIN-before-SFUN 路径有不同的既有设备依据：CPIN 在上电前可读，而强行启动空卡槽的协议栈曾导致 `mnphone_api.c:7048` 断言，见 E5 的 `modemmanager-09-unisoc-sim-presence-power.patch`。因此没有把 U30 的特殊上电预检照搬到 E5。

E5 本次“先有信号，随后模组消失”的静态排查另见 E5 仓库 `docs/E5-MODEM-DISAPPEARS-20261026.zh-CN.md`。连续 AT 超时后 MM 对象失效及 CP 断言是两类候选路径，仍不能认定群友触发哪一种。

## 验证与限制

新增假 AT/电源状态夹具模拟“SIM 插着但未上电”：修正前 4 项针对用例全部失败，旧脚本把两卡均跳过并误报 ready；修正后通过。

覆盖：两卡插入、单卡插入、空位置、上电失败、SIM busy、CME 100、用户禁用第二卡、已初始化路径、其他机型隔离与 SFUN=2 去重。所有测试不接触真实设备或发送真实 AT。

另外，扩散检查发现 `test_registration_scope` 的 procd 环境测试仍在读取已移除的旧 shell AT 守护结构，宿主机上会因寻找 `/opt/mu300/lib/modemd-service.sh` 而失败。已将夹具更新为当前 native modemd service 的真实 argv/env 接口，保留“每个 procd 实例只能设置一次 env”的检查；这不是设备运行时缺文件的证据。

最终回归执行了 90 项：89 项通过，1 项要求专用隔离容器和已核验 ARM64 bridge 的端到端用例因环境未配置而跳过。覆盖双卡初始化、独立 RF 开关、切卡事务、平台配置迁移、U30 服务布局、注册状态、native service 和移动网络地址恢复。Shell/Python 用例在本机可用的 dash、bash、BusyBox ash 下执行；`git diff --check` 通过。

```sh
PYTHONPATH=tests python3 -m unittest test_dual_radio test_sim_radio test_data_sim \
  test_platform_config test_u30air_integration test_registration_scope \
  test_modemd_service test_modem_pipeline test_cellular_mobility -q
```

本次只修改源码及测试，尚未提交、部署或打包。能够确认代码路径与历史 U30 测量有冲突，不能宣称已复现群友整机故障、修复所有新版无网络现象或完成硬件验收。

后续：2026-10-26 用户要求实机应用，已将此脚本及配套下行修复部署到其 U30 Air，正常重启后 SIM1 联网、IPv4/IPv6 与蜂窝实际收发通过；新增双待开关默认关闭。该次成功启动不代表真实复现了“未上电 CPIN=10”的所有故障条件。最终射频策略、范围和备份记录见 `DUAL-STANDBY-DEFAULTS-20261026.zh-CN.md`。
