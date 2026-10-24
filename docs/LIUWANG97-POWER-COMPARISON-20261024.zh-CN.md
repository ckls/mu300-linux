# liuwang97 fork 分支与省电差异复核（2026-10-24）

## 核查范围

本轮通过 `git ls-remote --heads` 获取分支列表，向现有仓库的
`refs/remotes/liuwang97/*` 获取对象；没有克隆新仓库、切换分支、合并或改设备。
不是只浏览较旧的 main。比较的本地 HEAD 为
`b47485341161088f34f6b4645a89416825c4c6a5`。

| 分支 | 本次固定 HEAD | 主要意义 |
| --- | --- | --- |
| main | 0b96af26 | 较旧基线，不代表后续优化集合 |
| cpu-load | b7474ed2 | 常驻服务优化；比上次 ccf89bb6 多一项 AT 锁忙/页面错误合并修复 |
| boot-speed | 1fb42beb | 原始启动优化与 USB os_desc 修复 |
| kernel-7.2-merged | 75295203 | 集成 PR 后补齐 7.2 的 PCIe 初次链路等待跳过 |
| lpintc-wake | 02833daa | LP_AP_INTC；最新增加 F50 验证说明，模块执行逻辑未新增改变 |
| pr/cpu-load | f5528dd8 | 整理后的常驻服务 PR，含测试修正；不能代替 cpu-load 的新增 b7474ed2 |
| pr/boot-speed | af2f37e4 | 整理后的启动 PR |
| pr/gadget-os-desc-double-free | 9f81f427 | USB 生命周期修复，最新增加 F50 验证说明 |
| fix/install-ps1-resume-function-order | ee1c4d50 | 安装器函数顺序修复，与省电无直接关系 |

完整 SHA、文件 blob、配置摘要和选取的源码快照保存在
`work/liuwang97-power-audit-20261024/manifest.json` 及同目录文件。

## CPU 深度空闲：默认没有禁用

八个包含后续 CPU 控制代码的分支均设置 `LOWLATENCY` 默认值为 0：

- `mu300-cpu lowlatency on` 才向 CPU0 各 `state*/disable` 写 1，保存用户选择。
- `off` 写 0 并删除该保存项。
- 启动回放 `lowlat_apply()` 只在保存值为 1 时禁用 CPU0 idle；未开启时保留内核默认。
- 不对其他 CPU 做同样的无条件禁用。较旧 main 没有这套后续可选功能。

证据：[cpu-load 的 CPU 控制实现](https://github.com/liuwang97/mu300-linux/blob/b7474ed2c152ec1fd94b5a0ceaab3a4d8c1339cb/rootfs/overlay/opt/mu300/bin/mu300-cpu)。

需要区分默认源码与作者调试设备：FINDINGS 218 记录他曾在设备 `/etc/rc.local`
禁用 CPU0 的 `cluster-pd`，用于绕过深睡唤醒延迟；LP_AP_INTC 修复的目标就是
允许保留 cluster-pd。不能把这段历史写成他从来没有关闭过深睡，也不能根据源码
判断作者现在每台实体设备的设置。
见 [lpintc-wake 的实验记录](https://github.com/liuwang97/mu300-linux/blob/02833daa0cc976698d42aa4a218c0a631f92b3fb/docs/FINDINGS.md)。

本地仍由 `mu300-lowlatency` 在 OpenWrt `mu300-hw` 和 systemd fixups 启动时
禁用 CPU0 各状态。这延续了此前用户指定的低延迟策略；当前 U30 Air 实测 core-sleep/
cluster-pd 无新增驻留、WFI 有驻留，详见同日省电检查。
LP_AP_INTC 已移植并实机加载，但没有因此自动改变该策略。

## 已覆盖的主要优化

- C AT I/O bridge、ucode modem daemon、唯一物理通道所有者和事件等待。
- 常驻原生 rpcd 系统快照/网速，短信签名变化才读取列表，隐藏页面停止刷新。
- procd 服务小核 cpuset；没有把“强制下线大核”当作这项优化的一部分。
- NO_HZ_IDLE、HIGH_RES_TIMERS、UCLAMP_TASK/GROUP、THERMAL_NETLINK 配置。
- LP_AP_INTC 唤醒模块；本地另增加映射失败的完整资源清理。
- eMMC 就绪探测、预读模块、无线顺序、随机池和早期串口输出等适用启动优化。
- 6.18/7.2 PCIe 初次链路等待的各自错误路径适配，保留恢复时正常等待。
- USB NCM/RNDIS os_desc 生命周期修复；没有反向覆盖本地 NCM TX 修复。

本地 LP_AP_INTC 与 fork 最新文件的差异仅为来源注释，以及本地已有的映射失败清理。
不能将 fork 新的 F50 实测文字当作漏掉了一个新版模块。

## 确实存在的行为差异

| 项目 | 对方实现 | 本地当前实现 | 评估 |
| --- | --- | --- | --- |
| CPU0 idle | 低延迟可选，默认保留内核 idle | 既有启动策略禁用 CPU0 状态 | 对续航最值得优先做受控验证的差异，不能凭代码估计节省功率 |
| LED 调度 | `.tick-hint` 记录下个到期时间，按到期/uevent 调度；安全核查为充电 30 秒、其他 90 秒 | sysd 每 5 秒启动既有 LED `sleep --if-due` helper | 可进一步减少周期唤醒与 fork；需要适配本地 U30 Air 的 50% 蓝/白规则、硬件呼吸、用户超时及充电事件 |
| 温控间隔 | 距阈值较远时自适应，内核已负责限频时最长 30 秒，独立 guard 最长 10 秒；接近阈值/持有限频/告警仍 5 秒 | 保留 5 秒保护周期 | 已知且有意保留的保护时效差异；进一步采用需保留当前温控所有权、错误处理与电池保护 |
| 定时器 slack | sysd、短信、NDP、温控等待阶段设置 500 ms，启动动作前恢复 | 不增加 slack | 是未采用的唤醒合并策略，会允许部分超时等待更晚返回；实际收益需测，不能宣称定时器已经一定合并 |
| early-recorder | `logread -l 300`；启动 90 秒后每 30 秒采样 | 读完整 logread 后截尾；90 秒后仍每 10 秒 | 小核亲和已移植；剩余两项没有采用。只作用于早期约五分钟记录窗口，不解释设备长时间运行后的待机负载 |
| 短信/NDP 兜底 | 事件驱动下短信同步默认 1800 秒、配置核查 600 秒；NDP 安全核查 300 秒，并退避无地址 solicitation | 短信仍 300 秒归档，NDP 10 秒安全检查，数据看守 30 秒 | 事件机制已移植，安全期限保留本地值；改变这些值会改变漏事件/断线后的最长恢复时延，属于行为取舍 |
| 整机 suspend | CONFIG_SUSPEND/PM_SLEEP/PM_AUTOSLEEP 已编译，autosleep 默认不启动，文档注明实验性 | 当前 U30 Air 内核 CONFIG_SUSPEND 未启用 | 独立于 cpuidle。不能只补配置就宣称 USB/Wi-Fi/基带/电源恢复可靠 |
| mu300-power | 提供空闲关热点/射频及 eco 下线核心等策略 | 沿用本地电源与充电入口，没有引入第二套所有者 | 不列作纯减开销优化；会改变联网功能和用户电源策略，本轮不建议直接搬入 |

其中 LED/温控/安全期限的大部分差异在上一轮移植报告中已经明确保留，并非本轮
才发现整批常驻服务漏移植。当前真实待机测量只有约 0.55%～0.63% 的八核总容量忙碌，
sysd 本身约单核 0.2%；不要承诺上述小项有数量级功耗收益。

主要来源：[sysd](https://github.com/liuwang97/mu300-linux/blob/b7474ed2c152ec1fd94b5a0ceaab3a4d8c1339cb/rootfs/overlay/opt/mu300/bin/mu300-sysd)、
[early-recorder](https://github.com/liuwang97/mu300-linux/blob/b7474ed2c152ec1fd94b5a0ceaab3a4d8c1339cb/rootfs/overlay/opt/mu300/bin/early-recorder)、
[内核配置](https://github.com/liuwang97/mu300-linux/blob/02833daa0cc976698d42aa4a218c0a631f92b3fb/upstream/mu300-mainline.config)。

## 新增且尚未覆盖的修复 b7474ed2

[提交 b7474ed2](https://github.com/liuwang97/mu300-linux/commit/b7474ed2c152ec1fd94b5a0ceaab3a4d8c1339cb)
在上一轮移植源 ccf89bb6 之后，包含两项相关可靠性修复：

1. 通道客户端锁被持有时明确返回 busy，采集轮次有界地每 250 ms 重试；若始终未能
   发出命令，不发布“AT 无应答”覆盖旧缓存。
2. 时间足够新的正常快档数据覆盖仅含错误的慢档缓存，清除旧 error 字段。

本地 `internal_at/round_at` 没有前一项的 held/asked/held_out 状态；页面虽有
自己的分阶段缓存合并，仍会把正常快档合进旧 error 对象并保留 error。
使用两边实际网页函数、相同的假输入（慢档错误 ts=100、正常快档 ts=101）离线执行：
本地结果保留 error，fork 结果移除 error。脚本为
`work/liuwang97-power-audit-20261024/compare-merge.js`。
这是离线数据合并复现，未在实体基带上制造 AT 锁冲突；不把它宣传为省电收益。

## 本轮产出边界

本轮仅刷新审查用 Git 引用、读取代码、执行无设备的合并函数对照、归档报告。
没有 cherry-pick、改生产代码、构建内核/固件、修改或重启 U30 Air。
后续优先级：CPU0 idle/低延迟选择及真实功率验证；适配 LED 到期调度；
单独处理 b7474ed2 的缓存/锁忙可靠性修复。其余降频率与定时器 slack 保留明确时效取舍。
