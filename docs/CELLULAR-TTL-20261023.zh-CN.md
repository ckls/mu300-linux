# 蜂窝 TTL 页面移植与验证

## 范围

页面参考 `dikeckaan/mu300-linux` 上游 `eab1802f` 的
`openwrt/luci-app-mu300/htdocs/luci-static/resources/view/mu300/ttl.js`。
保留 MIT 许可，随应用安装到 `/usr/share/licenses/unisoc-ttl/MIT`。
E5 与 MU300 使用相同的页面、JSON 适配器、规则引擎和服务脚本。

- 入口：蜂窝 → TTL，提供 64、65、128、自定义 1–255 和关闭。
- 默认关闭；设置保存在 `/etc/mu300/ttl.conf`，兼容 MU300 已有 CLI 配置。
- 应用启动、WAN 重连、系统重启均重新应用保存的设置。
- LuCI 包安装注册服务，移除前清理规则；E5 公共 UI staging 和 MU300
  rootfs 构建同时注册启动项。Ubuntu 原有 CLI 保留，OpenWrt CLI 转交同一引擎。
- 中、英、土三语；提交期间禁止重复点击，失败和断线明确提示。

## 规则与约束

本次 OpenWrt 实现明确使用 nftables，不运行 tc 能力探测，也不在错误后切换后端。
只修改 `inet mu300_ttl` 表，仅匹配蜂窝出口 `sipa_eth*`，同时设置 IPv4 TTL
及 IPv6 hop limit。批量替换规则为一个 nft 事务，不刷新其他表。

flow offloading 会绕过 postrouting，启用 TTL 时必须关闭软件和硬件流量卸载。
只记录由本功能从 1 改为 0 的选项，关闭时恢复这些选项；用户原本关闭的选项
保持关闭。该性能影响在应用设置前可见。fw4/uci/nft 出错不能返回成功。

使用 BusyBox 支持的 `flock -n` 互斥；第二个写入立即返回忙碌，用户可以重试。
新值只有在应用成功后才原子保存，规则失败不覆盖此前保存的值。

## 自动化验证

两仓库各运行 `python3 openwrt/tests/ttl.py -v`，每仓库 9 项通过：
IPv4/IPv6 规则作用域、输入校验、保留原先关闭的卸载选项、原子规则失败、
fw4 reload 失败后重试、uci 失败、进程重启恢复、默认关闭、并发互斥。

两仓库各运行 `node openwrt/tests/dashboard-ttl.js`，覆盖三语、非法输入、
重复提交、失败提示、保存后刷新及电源卡片实际渲染代码。
E5 公共 staging 测试通过，覆盖六个机型配置。

## 实机验证与边界

2026-10-23，仅在经过 SSH host key、机型和 eMMC 身份核对的 E5 上部署。
真实 RPC 读取成功；TTL 64 的 IPv4/IPv6 规则成功创建、读取、删除；
蜂窝 IPv4 ping 3/3，规则计数器实际增加 3 个包。测试后 TTL 关闭，规则清除。

没有建立 IPv6 外部连接，故不把 IPv6 语法/安装验证称为 IPv6 数据面验证。
MU300 本轮只有自动化和构建路径检查，没有连接其硬件部署。
E5 的卸载选项原本未开启，卸载关闭/恢复分支本轮通过隔离测试验证。

## 电源卡片

E5 同步 MU300 现有的电量条及带正负号的电池净电流，不将 USB 在线当成
正在充电。无电池时显示 USB/未知，隐藏电量条。电压统一保留两位小数，
修正 ucode 浮点序列化后出现 `3.7999999999999998 V` 的显示问题。
本轮实机返回 Charging、净电流 +12 mA；未进行拔 USB 后的放电实测。

本次未组装新的系统/安装器发布包，未提交或推送工作区更改。
