# U30 Air 4.4V 电池限制电压复核（2026-10-28）

用户确认原厂电池标签标称 3.85V、充电限制电压 4.4V。这是该电芯的标注，不能再把当前充电器的 4.304V 目标等同于电芯的额定充电上限，也不能仅凭标签断言原厂始终按 4.4V 充电。

## 只读实机结果

当前连接的 U30 Air UFS 版：

- BQ `constant_charge_voltage=4304000`，状态 Full。
- FGU 电量 100%、电池电压 `4260000`。
- 原厂传入 DT `battery/constant-charge-voltage-max-microvolt=4300000`。
- `batt_cap_learn/bcl_battery_count0`、`count1` 的 `bcl,battery-limit-charge-voltage` 均为 `4400`。
- `battery/ir-cv-offset-microvolt=100000`。

这次没有写充电寄存器、电量计、NV 或切换系统。上述属性区分充电器目标与电池实测值，不把 FGU 的其他电压属性当成充电芯片寄存器。

## 原厂参考源码

只读使用既有 `mu300-kernel` Docker volume 的 `zte-u30air` 源码，没有下载或复制内核。已登记版本为 `b50db5b6224c11db42a246e8fcdaad1e1d59f478`；它是原厂 GPL 参考，不能冒充当前 UFS 设备完全相同的运行固件。

- `drivers/vendor/common/power/battery_capacity_learning.c:1087` 读取 `battery-limit-charge-voltage`；约 1204 行通过 `POWER_SUPPLY_PROP_VOLTAGE_MAX_DESIGN` 返回选中电池的该值。这证明 4.4V 参数提供给上层，尚不证明它最终被下发给 BQ。
- `drivers/power/supply/charger-manager-sqc-v8.c:2481` 的补偿采用基础电压加平均电流乘电阻，并受上下界约束；其中 CP 状态另使用偏移。不能把 DT 的 100mV 参数直接理解为普通尾充固定加 100mV。
- `drivers/vendor/common/sqc_v8/sqc_charger_hal.c:1104` 将上层指定的充电电压传给 charger ops。最终 SQC 用户态策略选择何值仍需核对。

## 初轮结论（后续已核实最终配置，见下一节）

当前补丁确认对齐了 4.3V 基础配置及已核验原厂寄存器编码，不能据此宣称完整对齐原厂最终充电策略。此前 4.272V 结论已在旧文更正为基础目标 4.304V；本次进一步明确这也不是对电芯额定上限的证明。

需核实 SQC 上层如何结合选中电池的 4.4V、温度、老化和补偿决定最终电压，再决定是否修改 OpenWrt 控制。标签确认不能替代该步骤；本轮未将设备固定改为 4.4V。

## 本机 SQC 最终配置已提取并核实

用户要求对齐原厂后，从连接的 U30 Air UFS 版原始 super 分区只读解析 LP 与 EROFS，按 `/run/mu300/android-slot` 动态选择 vendor 槽位。只读取相关元数据和目标文件的块，电脑端保留稀疏元数据文件；没有复制整个 vendor、挂载 userdata、修改分区、写 NV 或切换系统。

本机 vendor 身份：`ZTE/U30Air/U30Air:13/TP1A.220624.014/20241014.163923:user/release-keys`。

| 原厂文件 | SHA-256 |
| --- | --- |
| `/vendor/bin/sqc_daemon` | `aa7263f496726b5e56b734c0f2076ddc91b621218647347afb3650e4f58f03be` |
| `/vendor/etc/.tp/sqc_charger.conf` | `4a20fee6985f14d2d8e149eb8ed348fa10a70dea2c66f60da5cefebba234eef2` |

压缩簇解压后检验 ELF；附带 `.gnu_debugdata` 的 XZ 校验通过。利用原厂附带符号与 ARM64 反汇编确认：

- `of_property_read_s32` 在 `0x125e8`、`of_property_read_u32_array` 在 `0x12854` 使用上述配置文件路径。
- `sqc_parse_dt` 在 `0x1160c` 等处读取 `sqc,max_vbat_mv`，不是从电池学习模块直接采用 4400。
- 实际配置 `sqc,max_vbat_mv = <4300>`。
- `sqc,fcv` 的 15 个值为 `4100 4300 4300 4200 4100 / 4200 4300 4300 4200 4100 / 4300 4300 4300 4300 4100`，最高也是 4300。

因此，“4.4V 电池标签或 BCL 额定参数意味着原厂最终必然设置 4.4V”的推断不成立；本机原厂 SQC 明确采用最高 4300mV 的策略。当前 OpenWrt 从基础配置取得 4300000，再按已核验的原厂 BQ 编码设置 `REG04=0x70`、目标 4304000，与这个正常充电目标匹配。之前 eMMC U30 Air 原厂 Android 的实时 `REG04=0x70` 采样也与之吻合，详见 BC1.2 报告。

没有将电池标签上限写成固定目标，也没有凭 BCL 参数增加 100mV。保留用户此前明确要求的电流配置与限充选择；电流偏好不用于推导电压。

## 配套驱动验证

从既有 `mu300-mainline-clean-tf-7-2` volume 只读核对已准备的两个驱动，分别运行现有 `tests/bq256xx_stock_cv.py`，均通过：4300mV 对应 4304000µV、901 个输入的寄存器编码、其他位保留、低压电池、缺少 battery-info、I/O 错误及非电池板隔离。两套源码不是相同文件，不跨内核替换模块。

- 7.2.8 驱动 SHA-256：`81dd27a259bfff80cab9ee05b92dfef543132d73cf11d74189f99f8a33e00094`。
- 6.18.54 驱动 SHA-256：`abb0b2dd735938675d7ae711d4b31301554e591e365b6aacd95d323262fe08e2`。

本次对齐结论限定为本机固件的充电电压来源和正常充电目标；不冒充移植完成整个 SQC 温度/老化/充电阶段管理器，也不以原厂的一次采样代替完整充满测试。本轮充电电压无需再修改，没有重新编译内核、刷入或改写设备充电参数。调查资料在 `work/u30air-charge-voltage-20261028/`。
