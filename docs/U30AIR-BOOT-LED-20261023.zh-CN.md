# U30 Air 开机电池灯轮换

用户反馈启动加速后看不到电池灯红、白、蓝轮换。检查当前源码和部署前备份的
initramfs `/init`，均未找到该机型的 RGB 开机轮换实现；U30 Air 的 `led-status boot`
分支只设置网络灯和电量灯。这能确认当前入口缺少轮换，不能证明优化删除了旧灯效，
也没有把启动变快导致 bootloader 灯效变短的猜测写成结论。

## 修改

在共享 rootfs 的 `mu300-led` 中增加仅 U30 Air 使用的开机轮换操作，
`u30air-led-status boot` 启动轮换。电池灯的 PMIC 通道为 `sc27xx:red`、
`sc27xx:green`（实际白色）、`sc27xx:blue`，沿用现有已确认的机型接线。

- 每帧使用现有 LED 互斥锁，休眠时释放锁；通过随包 BusyBox 的 `usleep` 控制间隔，
  不依赖 OpenWrt 精简版 `sleep` 支持小数。
- 电池事件继续记录正常电量和充电状态，开机轮换期间不覆盖 RGB 帧。
  网络和 Wi-Fi 灯仍独立更新；亮度、电池灯开关和休眠设置仍生效。
- 既有 `mu300-post` 开机完成通知或蜂窝 online 通知结束轮换，恢复正常电池显示。
  每个 worker 使用独立 token，每帧在锁内复核；旧 worker 不能在交接或重新开始后写灯。
- 温度告警取消开机轮换并保留优先权。轮换仅在启动阶段运行，不增加常驻轮询。
- 共享打包和更新路径会携带这两个 rootfs 文件；无需重编内核或图形安装器。

## 验证

相关测试 31 项：30 通过，1 项需要 ucode 的既有无线测试在本轮主机环境跳过。
覆盖 RGB 帧、事件刷新、正常电量交接、旧 token、worker 退出、灯光开关和亮度、
温度告警优先级，以及原有充电呼吸灯、超时、网络灯、V50 灯和启动顺序检查。

已部署到用户连接的 U30 Air，实机逐帧采样确认出现 `(255,0,0)`、`(0,255,0)`、
`(0,0,255)`；停止后 worker 退出。设备配置及 Android boot A 的 SHA-256 不变。
随后实际重启：SSH 重新可达，WAN 正常，热点在内核启动约 20.78 秒进入转发状态，
没有新的 BUG/Oops/WARNING/panic。正常状态为 online-5g；蓝色电池灯恢复硬件充电
呼吸曲线，开机 token 和 worker 均已消失。实际肉眼观感仍需用户确认。

- [自动化回归](../out/build-logs/20261023-055937-u30-boot-led-regression-81514/command.log)
- [实机灯色与交接](../out/build-logs/20261023-055950-u30-boot-led-live-91352/command.log)
- [实际重启](../out/build-logs/20261023-060002-u30-boot-led-coldboot-91371/command.log)

原始采样位于忽略目录 `work/boot-led/`；部署前脚本备份保留在设备
`/mnt/mu300-disk/.mu300/backups/boot-led-20261023/`。完整部署清单同步两个新源码哈希。
本次没有构建发布包，也没有修改 Android 启动镜像、userdata、GPT 或 NV。

## 充电低电量颜色补充

按用户补充的 U30 Air 灯光行为，充电且电量低于 10% 时使用红色硬件呼吸灯；
10% 至 49% 仍为蓝色，50% 起仍为白色。充满常亮、拔线、非充电电量提示和其他
机型不改。此处低电量规则的依据是用户反馈，未额外宣称已从原厂驱动中复核。

25 项相关回归全部通过，新增检查 0%、9%、10%、49%、50% 及颜色往返切换、
亮度、灯光关闭和拔线后 FGU 状态滞后的情况。已部署单个共享脚本并刷新当前
电池灯，无需重启；实机尚未降至低于 10%，低电量红色呼吸尚待实际电量验证。

- [低电量回归](../out/build-logs/20261023-060252-u30-low-charge-led-91419/command.log)
- [部署及当前电池状态](../out/build-logs/20261023-060316-u30-low-charge-led-live-2513/command.log)

旧脚本保留在设备 `/mnt/mu300-disk/.mu300/backups/low-charge-led-20261023/`。

## 电池开机时轮换前的全灭间隔

用户继续反馈：红白蓝轮换存在，但开机后先全灭数秒。读取当前 U30 Air 的历史
启动记录，initramfs 在约 1.29 秒切换根目录，常规硬件服务约 9.23 秒进入。
原早期 USB preinit 已调用 `led-status boot`，但 `boot on` 没有初始化亮灯时限；
无外部电源且尚无 `.awake-until` 时，帧被 `awake()` 当成休眠而写成 0。
这是一项可确定性复现的代码缺陷；上述历史记录不是第一帧的光学实测时间。

修复使用现有共享 LED 控制器：

- `boot on` 建立原配置的亮灯时限，并在现有互斥锁内同步显示第一帧，再启动轮换
  worker。重复通知保持幂等，不延长已开始的开机时限。
- 新增 `04_mu300_early_leds`，在 `preinit_essential` 先于 recorder 和 USB 设置
  通知开机灯；移除 USB 钩子里的灯效调用，电池开机不再依赖 USB 接口是否存在。
- 复用同一帧函数、亮度、灯光开关、温控 owner 和 token 交接检查。没有新增常驻
  服务、等待或 initramfs 写灯实现；现有 Linux boot 镜像无需更换。

新增测试在 worker 尚未运行时检查电池供电第一帧、配置禁用、亮度、重复通知和
原时限；旧实现会因没有亮灯时限而失败。另检查早期钩子注册、USB 解耦及 Unix
行尾。宿主组 39 项中 31 项执行通过；8 项缺少 ucode 的用例随后在既有 ARM64
容器补跑全部通过，共 39 项均有实际通过结果。覆盖原灯效、充电低电量颜色、
温控优先权、按键、F50/V50 和板级偏好。

- 复现：`out/build-logs/20261023-133200-u30air-led-dark-gap-reproduce-23466/command.log`
- 修复后回归：`out/build-logs/20261023-133243-u30air-early-led-regression-23496/command.log`
- 原生补跑：`out/build-logs/20261023-133332-u30air-early-led-native-33759/command.log`

已在核验身份的 U30 Air 更新四个启动文件，先核对原文件与提交版本一致、备份，
再校验 shell 语法并替换、回读 SHA-256。17 份 UCI 配置文件摘要不变，未重启或
触发当前开机灯，没有修改 boot、misc、GPT、NV 或充电配置。备份位于：
`/mnt/mu300-disk/.mu300/backups/early-leds-20261023-133442/`。

实际冷启动和电池独立供电的第一帧时刻仍待用户观察；本轮没有宣称从按电源键
到 Linux 接管前的 bootloader 阶段也消除了全灭。没有组装新包或提交本轮修改。
