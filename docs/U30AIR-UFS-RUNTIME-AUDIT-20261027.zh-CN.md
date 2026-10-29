# U30 Air UFS 启动与运行只读检查（2026-10-27）

后续处置见 [SIPA 修复与同机原厂无线对照](U30AIR-SIPA-WIFI-20261027.zh-CN.md)：
SIPA 已修复部署；两条无线拒绝回包在同机原厂 Android 中也已实测确认，
不能将下文初步疑点当作 OpenWrt 新引入的缺陷。

## 范围与结论

对象为已安装 OpenWrt 的 U30 Air UFS，Linux 7.2.8 #73，根分区
`/dev/sda76`。本轮通过 USB 网络 SSH 读取现有日志、sysfs、进程栈和
现有状态缓存，没有重启、重拨、发送测试 AT、切换射频、修改充电或存储参数。
用户确认 SIM 欠费，本轮不把注册失败、WAN 未连接视作驱动缺陷。

UFS 和根文件系统在观察窗口内正常，但不能据此认定整机所有驱动无缺陷。
发现 SIPA 未启动线程的长期 D 状态告警，以及无线固件拒绝初始化命令，需分别处理。

## 已确认正常的项目

- 同一次启动持续到 1362.76 秒，检查期间 boot ID 未变。
- initramfs 记录加载模块 26 个、失败 0 个，1.43 秒进入 switch_root；
  该数字不代表完整系统、热点或蜂窝联网耗时。
- UFS 绑定 `ufshcd-sprd`，SCSI 设备状态 `running`。根分区容量约 7.8 GiB，
  ext4 保持 `rw,noatime`，`errors_count=0`。
- 完整内核日志未见 UFS timeout、ext4 error/warning；未见 SIPA overflow、
  `push link fail` 或 `CMD_TX_DATA` 固件错误。此结论仅覆盖已有日志和当前负载。
- AT owner bridge connected，六个命令 broker 均 open/idle，队列 0、silent 0；
  两个 URC 通道 open，没有“模组消失”的证据。
- USB 网络有实际管理流量；热点处于 ENABLED，信道 36、5180 MHz。
- CPU 调频策略均为 schedutil，温区约 39–41°C，电池温度约 33.4°C。
  5 秒 CPU 总体忙碌率约 13.34%，iowait 为 0%；这个短样本不能代表续航。
- 接电脑时充电器输入限制 500 mA，实际充电器 CV 属性 4.304 V。
  这不能用于判断独立充电器的最大充电功率。

## 确认存在的异常现象

### SIPA 线程未启动，产生 hung-task 和负载污染

`sipa-free-1`、`sipa-fill-recv-1` 均处于 D 状态，栈仅包含
`kthread → ret_from_fork`，各只有 1 次 voluntary context switch。
内核累计报告 10 次相应 hung-task，随后达到告警次数上限。

代码对应 `upstream/modules/sprd_modem/sipa_v3/sipa_skb_send.c`、
`sipa_skb_recv.c`：创建使用 `kthread_create()`，启动依赖之后的
sender/receiver resume。当前蜂窝未建立数据连接，线程仍停在首次启动前。
这可以解释 D 状态告警及 load average 被抬高；不是 UFS I/O 堵塞的栈，
也不能仅凭此认定蜂窝传输死锁或两个线程正在消耗 CPU。

后续修正应核对首次启动、资源恢复和退出的完整生命周期，不应通过关闭
hung-task 检测、关闭休眠或在硬件未准备时强行启动工作线程掩盖现象。

### Wi-Fi 初始化命令被固件拒绝

两轮无线初始化中，第三段 RF INI 下载各出现一次
`CMD_DOWNLOAD_INI / SPRD_CMD_STATUS_UNKNOWN_ERROR`；
另各出现一次 `CMD_POWER_SAVE / SPRD_CMD_STATUS_ARG_ERROR`。
热点最终启动成功，但不能把这些回包视作配置已经生效。

运行固件报告 drv_version=2、fw_version=2、fw_ver=57488。
RF 段格式及功耗/功率子命令需要结合本机原厂驱动核对；现有回包没有给出
POWER_SAVE 的具体子类型，不能据此断言全部省电功能失效。

### 其他待核对项

- FGU 的 `constant_charge_voltage` 属性为 4.712 V，与实际充电器的
  4.304 V 属性不同。前者不是实测电池电压；需核对属性实现与电池表，
  目前没有实际以 4.712 V 充电的证据，未修改参数。
- `bss_load_update_period=60` 导致约每 6 秒一次 change_beacon；
  最后日志快照共 210 次。确认有周期更新和日志，但不能据此认定会掉线。
  当前没有连接的 Wi-Fi 客户端，未验证吞吐、延迟与多客户端稳定性。
- 启动时有 UFS 校准数据初次获取失败、FGU IIO 获取失败，之后设备成功绑定，
  最终 deferred 列表为空。另有 PCIe 重试、遗留 eMMC 控制器探测失败及
  regulatory.db 缺失等启动告警；需要分别对照原厂和初始化顺序，不能统一当作 UFS 故障。

## 证据

本机调查文件保存在
`work/u30air-ufs-20261027/runtime-audit-211319/`，包含完整 dmesg、
运行状态、线程栈、CPU 短采样和最终健康快照。日志用于本地诊断，不应直接公开
可能含设备身份的信息。本次仅新增检查记录，没有修改设备驱动或配置。
