# 看板未插卡与射频关闭的状态区分（2026-10-27）

## 原因与改动

主页原先仅按 CFUN=0 显示“无线电已关”，未读取已有的按槽 SIM 状态。无卡省电时射频关闭，使物理缺卡被显示成了射频设置。

现在 sysinfo 的 modem.sims 返回两个槽位的 `{slot,state}`，主页按正在查看的槽位选取。确认 absent 时优先显示“未插卡”，清除该次显示中的旧运营商、身份、小区和信号；缓存未知不猜无卡，已插卡且 RF 关闭仍显示“无线电已关”。缓存对象不原地修改，原有射频开关、AT 时序与刷新频率不变。

## 两仓库的数据来源

- MU300：复用现有 AT owner 的 `/run/mu300-registration/simN.json`；校验槽号、状态以及 SIM 已上电标记 `sim-powerN`。owner 不存活时返回 unknown，不因空 ICCID 或 CFUN=0 推断 absent。
- E5：复用 `/run/t551m-sims.json`，核对行槽号、明确的 present/registration、monotonic updated 与 15 秒有效期；过期、未来时间、错误类型或无 owner 返回 unknown。没有新增 HTTP 路径上的 AT 请求。
- 返回两个槽位是因为 sysinfo 为共享请求，而用户可以查看非上网卡；不能只返回当前数据卡的缺卡状态。
- common.js 补齐中文、英语和土耳其语的“未插卡”。

## 验证与范围

- 两仓库浏览器回归覆盖：缺卡覆盖 RF-off/旧 RAT、清除旧身份信号、已插卡 RF-off、未知不猜缺卡、槽位隔离、重新注册恢复，以及已有的慢/快缓存合并场景。
- MU300：9 项 dashboard info、14 项 native snapshot、缺卡翻译专项及快捷控制通过。
- E5：2 项 SIM presence、8 项 native snapshot、缺卡翻译专项及快捷控制通过。
- ucode 测试复用已有 `mu300-openwrt-ra-native:25.12.5` 容器，仅访问临时夹具；不是物理插拔验收。
- 通用 MU300 翻译测试另发现 HEAD 原有 TTL 菜单缺少 PO 条目，未计为本次缺卡翻译检查通过，也未在本次顺带改动。

本次已按设备存储身份复核后热应用到连接的 U30 Air UFS，实机 sysinfo 返回 SIM1 absent、SIM2 ready；AT owner PID 前后相同。没有在 E5 实机部署，也没有为此重新发布包。U30 部署回执位于 MU300 工作区 `work/u30air-ufs-20261027/sim-display-deploy.json`，设备只保留一份本次三个文件的小备份。
