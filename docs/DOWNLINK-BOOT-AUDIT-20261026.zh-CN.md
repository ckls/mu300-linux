# 开机长时间无下行：对群友分析的源码核对

2026-10-26。输入为用户粘贴的二次分析和时间线，没有对应原始日志、明确机型/包版本、持续发流量期间的接口/AT 快照。本次未连接或改写设备，未主动重拨、加载驱动或修改射频。

## 可以直接纠正的解释

### flag=2 / WWAN_DL 2→0 本身不是异常

`upstream/modules/sprd_modem/sipa_delegate/sipa_dele_priv.h` 定义 `SMSG_FLG_DELE_RELEASE=2`。
`sipa_dele_on_commad()` 将其交给 `sipa_dele_r_user_rls_cons()` 释放之前申请的下行资源引用。

这不等同于“modem 惩罚性撤回下行”，更不代表 PDP 被去激活。原厂 Android 的既有抓取也出现 REQUEST→GRANTED→RELEASE 的正常循环，见 `docs/FINDINGS.md` §13f、§13g。空闲时 IPA 休眠与资源释放不应被改成始终持有；否则会破坏省电行为。

### 当前 watchdog 没有“发现 RX 不增长就重拨”的条件

`mobile-data:watch()` 实际检查：

- PDP CID 是否仍激活；两次确认失活后才走现有重连。
- AT 无应答或回复无法识别时保留链路，不拿超时证明断网。
- PDP 活着但 IPv4 地址改变/内核地址缺失时，OpenWrt 路径请求原地 renew。
- CFUN 明确为 0 时，才尝试原有射频恢复；查询失败不冒充射频关闭。
- 用户 ifdown、切卡、pending 的状态仍受门控。

该函数没有按照 RX 字节数判断故障。因此仅看到 t=268 秒 RX 增长，不能推导为“watch 发现无下行并重拨成功”；必须有对应 `mobile data lost`、netifd setup/teardown 或 PDP 日志。

### 当前拨号入口已在 CGACT 前加载 delegate

`mobile-data:up_locked()` 在注册确认后、配置/激活 PDP 前同步调用 `sipa-dele-start`。OpenWrt 的 `extra-modules` 已让出加载权，不再后台竞争；不能仅按二次分析认为当前源码根本没有这项顺序保护。

但是 `insmod()` 返回和连接线程已经运行不是同一时刻，所以 t=18.4 的线程日志晚于 t=18.2，既可能反映异步运行，也需要核对具体是哪条线程消息、实际版本和之前是否已经加载，不能只靠相邻时间就确认根因。

## 确认存在的就绪判断缺口

`sipa-dele-start` 当前的等待逻辑只匹配：

```text
channel 5-120 send open msg
```

在真实 `sipc/smsg.c:smsg_ch_open()` 中，这条日志打印在 `smsg_send()` **之前**。之后才发送 OPEN、等待对端 OPEN_MAGIC，最后打印 `channel 5-120 success` 并将状态改为 OPENED。

因此“发送 OPEN 的日志存在”不能证明通道握手完成。现加载器还有两个相关边界：

- 等待 30 轮后找不到发送日志，也只是打印提示并返回 0。
- 看到 `sipa_dele` 已在 `/proc/modules` 就直接返回 0，没有核对连接线程状态。

这是可从源码确认的成功判断过早。**尚未证明它触发本次群友的分钟级无下行**，更不能由 flag=2 证明。正确修正应使用连接/资源准备完成的真实状态，正常已就绪路径立即继续，失败有明确错误，不加入固定启动等待或按时间重拨。仅把另一个历史 dmesg 字符串当作永久就绪标记也不可靠：重置后状态可能已变化，运行久后日志还可能被覆盖。

## 驱动层另一个待确认的竞争窗口

`sipa_delegator_start()` 先唤醒连接线程，再创建 producer、建立依赖和注册 consumer 回调。线程有机会在图和回调未全部安装前接收命令。既有修复已处理 `-EINPROGRESS`、运行时 PM 正返回值及重复 ENABLE；不能把这些已经存在的修复重复叠加。

这只是调度顺序上能看到的窗口，不是已经复现的本次根因。若要修改，需验证请求/完成回调、失败清理及两种内核上的生命周期，不能仅交换一行就声称修复了无下行。

## 本次结论

不采用“开机 90 秒重拨一次”。目前足够确认加载器的就绪判据不完整，也足够否定“flag=2 就表示异常撤权”和“RX 后来增加就证明 watchdog 重拨”这两项推导。真实无下行还需要区分 PDP 已失活、旧地址、选错 SIM/CID、delegate 通道失败、SIPA 恢复或实际没有入站流量。

上述是最初静态分析的边界；用户随后明确要求补齐缺口，实际落实如下。仍不宣称已经实机复现并根治该群友的分钟级故障。U30 冷启动无卡误判是另一项已离线复现并修正的问题，见 `U30AIR-NO-NETWORK-AUDIT-20261026.zh-CN.md`。

## 已落实的修正

### 内核提供真实就绪状态

CP delegate 新增两个只读属性，位于绑定设备的 `sipa_delegate` platform driver 目录：

- `sipa_dele_ready`：0 表示通道尚未完成握手，1 表示通道已可处理命令，负值记录 OPEN 失败的 errno。
- `sipa_dele_wait`：已就绪立即返回 `1`；未就绪则在内核 waitqueue 上等待 OPEN 完成/失败，保留旧加载器的三秒握手预算；超时、中断及失败返回错误。

它们不申请/固定持有 WWAN_DL，不将 RM 的正常 RELEASE 当成故障，也不增加空闲时定时器、禁休眠或电源复位。

连接线程在 `smsg_ch_open()` 成功且完成原有 `on_open()` 后发布就绪；CLOSE 或明确的通道 FREE/缺失清除就绪，新 OPEN 后重新发布。其他瞬时读错误不能推导为断开，同时失败读取不能再拿未填充的 `mrecv` 继续分派命令。

`sipa_delegator_start()` 现在先建立 producer/依赖并注册 consumer 完成回调，再唤醒连接线程，避免第一条 CP 资源请求赶在回调安装前。原有 `-EINPROGRESS` 成功语义保留。CP 初始化先启用 PM、建立 sysfs，再启动；失败只清理尚未运行的线程、工作队列、PM 和分配对象，不留下成功状态或运行线程引用已释放对象。

### 拨号只认真实握手

- 加载器完全移除 dmesg 就绪判据，读取 `sipa_dele_wait`。
- 模块已加载时也要核对通道，不能因 `/proc/modules` 有名字就返回成功。已就绪时该检查立即完成。
- `mobile-data` 每次进入 PDP 建链前均通过此门控；第一次失败后下一次重试也不能绕过去。
- 新加载器只接受配套内核 ABI，缺少/歧义/失败就明确报错，不静默回到旧的日志扫描。
- 打包及模块校验检查 `sipa-dele.ko` 含两个 ABI 标记，阻止“新加载器＋旧模块”组合进入后续正式包。升级这些文件后须重启使用新模块，不能只热替换脚本就当作已经生效。

### 另修复等待错误 SIM 的问题

原加载器固定通过默认 nr1/slot0 发 `CGATT?`。SIM2 是上网卡、SIM1 未附着时，可能等错卡而拒绝加载 delegate。
现在从共享 `mu300-sim-env` 取得上网卡，使用其既有 shared owner、`MU300_AT_DAEMON_ONLY=1` 与显式 `SPACTCARD=<slot>;+CGATT?`；没有增加串口读者或抢占 nr2/nr5 拨号端口。

## 回归及编译

生产回调 C/UBSan 测试覆盖：资源图/consumer 回调先于首条线程消息、各失败步骤不启动线程、异步依赖返回值、PM 与 sysfs 准备顺序、READY 快路、等待成功/失败/超时/信号中断、CLOSE 竞态、瞬时读错误、通道重新 OPEN。

真实 shell 脚本夹具覆盖：上网 SIM1/SIM2 的端口与命令前缀、首次/已加载模块、缺少 ABI、读取失败、非法状态、没有附着时不加载、已就绪不 sleep，以及无论已加载与否门控失败都到不了 PDP 激活。没有硬件访问。

扩散覆盖双卡初始化、用户 RF 权限、切卡、配置迁移、U30 服务布局、注册与移动地址恢复、打包完整性。共 123 项通过，1 项无线 ucode 环境未配置而跳过（分组执行，其中最后补充了一个真实 PDP 门控用例）。

使用现有 `mu300-mainline-clean-tf-7-2` volume、`mu300-mainline-build` 镜像及规定 `tools/build-release.py run` 入口，复用原有 Image 与内核对象，重编维护的两套 modem 模块并刷新完整模块清单。没有复制内核树、重新下载或重编未变的 Image。

| 配套内核 | 最终编译日志任务 | sipa-dele.ko SHA256 |
| --- | --- | --- |
| 7.2.8 | `out/build-logs/20261026-135404-sipa-ready-72-final-91494/` | `35ec5dddb43fd0da80d42a5f3e5217026ba226ac93ca7a0f44d7a528060c2129` |
| 6.18.54 | `out/build-logs/20261026-135547-sipa-ready-618-final-6496/` | `248be8a17880dd7b439c981a6b5c4012be0e83eec465a1c44f95fdc61d36202b` |

两套均通过模块哈希、vermagic、BTF 和完整依赖检查；Image SHA 与改动前相同。最终交付目录仍为 `/home/kano/openwrt-build/kernels/mu300-{7.2.8,6.18.54}/`。

E5 的独立公共驱动补丁 `devices/common/sipa-data-path.patch` 已有“资源/回调设置后再唤醒线程”的保护，其基线、reset 工作队列和加载流程不同，本次没有把 MU300 的加载脚本或 sysfs 依赖照搬过去。

尚未部署设备、打包完整固件或提交；离线回归和编译不能冒充硬件验收。不承诺固定网络恢复时间，也没有采用 90 秒一次性重拨。

## 后续 U30 Air 实机应用

2026-10-26 已按用户要求部署 U30 Air 的 7.2.8 配套 delegate 模块和加载脚本，并正常重启。boot 内核 Image、SIPC/SIPA 核心模块均与构建基线哈希一致；没有刷新 boot 或改变 kernel Image。

实机 `sipa_dele_ready=1`，已加载模块的就绪检查返回成功；拨号日志先输出 `delegate channel and resource callbacks ready`，WAN 随后成功获得 IPv4/IPv6，指定蜂窝接口的外网 ICMP 三发三收。该结果验证了本机启动及新接口，不等于复现了群友分钟级无下行故障。双待设置及备份见 `DUAL-STANDBY-DEFAULTS-20261026.zh-CN.md`。
