# U30 Air 提前停充与慢充：原厂参数对照（2026-10-22）

用户报告：设置 90% 上限，约 84% 就显示 Full；另一台约 91% 停充，需要拔插才能继续。
本轮连接的 U30 Air 当时为 91%、Charging，尚未现场捕获提前 Full 或超时故障。

## 已确认的驱动差异

1. 旧补丁把 vendor BQ 的充电电压上限固定为 4.208 V，并按芯片默认值初始化。
   本机原厂 battery 节点配置是 4.3 V，SDP/CDP/DCP 的有效 JEITA 档位也为 4.3 V；
   原厂驱动从 battery-info 读取该值。旧值来源于单次寄存器快照，不能作为完整充电策略。
   过低的 CV 会提前进入恒压小电流阶段，也可能在电量百分比尚低时终止充电。
2. 原厂 BQ probe 关闭 REG05 bit 3（硬件充电安全计时器），现有主线适配却没有关闭。
   长时间慢充触发超时可以解释需要拔插的部分现象，但本轮没有捕获到实际超时状态，
   不能把用户所有停充都归因于计时器。
3. 本机限充服务当时 `enabled=0, paused=0`，运行状态没有 owned/stopped；
   因此该快照不是网页 90% 上限主动停充。离线回归另验证了 84%/Full 不应触发 90% 限充。

## 原厂证据

机型 U30 Air SSV，已有固件记录 `U30Air_SSV1.0.0B14`；原厂模块 vermagic
`5.4.254-android12-9-g9444efdc6885`。从本机 Android A 槽 `vendor_dlkm_a`
只读提取（super 内单个 5.2 MiB EROFS extent），未写入 Android、NV 或电量校准区。

| 模块 | SHA-256 |
| --- | --- |
| sqc_bq2560x.ko | ce42c87c42f9ed7e5b5aba8277d4245c03c2c41a569e8ca24d749f07bc3a0efc |
| charger_policy_service.ko | 808b23dce5aee9886df868cd796c8382105b9d99cc80bd2240f8a93fc7b2ac1e |
| sc27xx_fuel_gauge.ko | b677aef2019ac95da686bbf80ce72f2a3f12f22bc5a151e9f6bd187f1e13f074 |

`sqc_bq2560x.ko` 的 `bq2560x_charger_probe` 起点 0xd30，
0x1b08（probe+0xdd8）执行 `and w2,w8,#0xfffffff7` 后写回 REG05，关闭安全计时器。
对应原厂源码 `sqc_bq2560x.c` 的硬件初始化同样从 battery-info 取 CV、关闭安全计时器。
本机实时 REG04=0x58（4.208 V）、REG05=0x8f（终止开启、安全计时器开启），印证旧行为。

## 修复范围

新增公共构建补丁 `0023-power-bq256xx-stock-battery-cv-and-timer.patch`，用于 7.2.8、6.18.54：

- 仅原有 battery-policy 隔离的 `ti,bq2560x_chg` 路径使用本机 battery-info 的 CV，
  限于芯片能力；缺少有效配置时保留芯片默认值，低压电池不会被统一提高到 4.3 V。
- 本机 4.3 V 按 BQ 的 32 mV 步进向下编码为 **4.272 V**。
- 对齐原厂关闭硬件安全计时器，保留 EN_TERM、TS/NTC、过压/过温保护和其他寄存器位。
- 保留现有 1.98 A 充电电流上限、USB 输入识别/限流、用户上限、暂停和一次充满操作。
  电脑 SDP 的 500 mA 不应被强行提高到充电器电流。
- 不强制改百分比、不添加循环重启充电、不修改回充电压、不增加后台轮询。
- F50/V50 仍在首次硬件访问前排除电池路径，普通上游 BQ 节点保持原初始化行为。

## 验证

- `tests/bq256xx_stock_cv.py KERNEL_TREE` 编译实际驱动初始化/CV 函数，覆盖 4.3 V、
  低压电池、芯片上限、无效/缺少 battery-info、I/O 失败及非 vendor 节点；核验
  终止、温度、回充、输入及升压位不被误改。
- `tests/stock_power_driver.py KERNEL_TREE` 回归原厂电量编码、满电电气条件与无电池板隔离。
- `tests/test_charge_control.py` 使用隔离 OpenWrt 容器执行真实 ucode，覆盖用户限充、
  暂停、一次充满、插拔/OTG、无电池板，以及提前 Full 不能冒充用户上限的场景。

完整充电周期、90% 上限停充点、低电量起充及原故障的长期不再出现仍需实物验证。
内核/模块的编译和短时检查不等同于上述验证完成。

## 本轮编译与实机部署结果

- 7.2.8、6.18.54 完整 Image 和所有配套模块编译通过，两个实际准备树的驱动测试通过。
- 实际 ucode 限充回归 **12 项通过**，包含新增的 84%/Full、90% 上限边界。
- 核验 U30 Air 身份、eMMC CID 和动态启动槽后部署 7.2.8。全部根模块及 initramfs
  同内核版本模块记录一起替换；原 init、cmdline、vendor fallback、启动日志区保留。
  写入回读、配置哈希及 misc 未改变校验通过，随后正常重启。
- 重启后所有部署模块哈希校验通过；BQ REG04=`0x68`（4.272 V）、REG05=`0x87`
  （终止开启、安全计时器关闭）。电池 92%、约 4.199 V、+145 mA、25.4°C、Charging/Good。
  对比前值只证明设置生效，不把电脑 USB、近满电时的电流当成充电器最大速度测试。
- 电脑 SDP 输入仍为 500 mA，充电电流上限仍为 1.98 A；用户限充、暂停、热点及网络
  配置哈希不变。5 GHz/80 MHz 热点恢复 ENABLED，WAN 自动获取 IPv4，USB 管理恢复。
  未见新的 BTF、Oops 或存储 I/O 错误；原有 SIPA 组播告警不属于本轮充电修复结论。
- 实机备份：`/root/hotfix-backups/u30-stock-charge-20261022`。
  电脑端寄存器、只读原厂模块及部署回执：`work/u30air-charge-early-full-20261022/`。
  构建日志：`out/build-logs/20261022-112207-u30-stock-charge-49312/`。

本轮未生成发行包、未提交 commit，F50/V50 未刷写；6.18 为编译验证，未刷入本机。

## 尚未移植：原厂长时间插电保护

用户补充原厂长期插电会主动停充。继续核对后确认，这与 BQ REG05 的芯片安全计时器
是两套机制，不能用重新打开芯片计时器代替原厂软件策略。

本机原厂 DT 的 `charger_policy_service` 启用了 `expired-mode-enable=1`，
`timeout-seconds=57600`（16 小时）、`expired-max-capacity=90`、
`expired-min-capacity=70`、`have-power-path=1`、`low-temp-enable=1`。
原厂模块存在 expired 状态、超时处理、禁充及恢复的实现。

对应厂商源码 `drivers/vendor/common/power/charger_policy_service.c` 以 boottime
维护 `charging_begin`，超时进入 overtime 策略，另有拔电、低温及恢复充电分支。
**不能仅凭 DT 的 90/70 两个值就简化成“16 小时后 90% 停充”**：有 power-path
的源码分支在部分状态使用上下阈值的中点，还区分充电开关与输入路径开关。
具体状态转换应继续与本机原厂二进制核对后移植。

当前 OpenWrt `charge.uc` 只有用户限充、手动暂停和一次充满，**没有原厂 16 小时
软件保护**。本轮关闭芯片计时器符合原厂芯片初始化，但不代表这层长期插电保护已完整
对齐。它是明确待补的功能，不把长期插电后的原厂主动停充全部判作硬件故障。
