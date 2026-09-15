# 日常维护与滚动升级

本页说明完整更新方法、板级组件的保护措施和各次测试范围。本版最终镜像的维护结果见后文及 [发行说明](RELEASE.zh-CN.md)。更新事务成功或文件哈希不变不能代替更新后的硬件复测，也不能保证未来版本兼容性。

日常更新使用完整事务：

```sh
sudo pacman -Syu
sudo reboot
```

按照 [Arch 系统维护说明](https://wiki.archlinux.org/title/System_maintenance)，不要使用 `pacman -Sy` 后仅更新个别软件包的部分升级方式。普通 Arch Linux ARM 软件来自其仓库；板级内核、无线模块、GPU 模块与专用用户态来自本项目的 T5 软件包。没有用宽泛的 `IgnorePkg` 冻结整个系统，也没有替换 Arch 的 Mesa、libglvnd 或系统 Xorg。

## 驱动与启动文件的保护

板级内核与外部模块采用匹配的 T5 版本，GPU 用户态依赖对应的 GPU 模块。更换 BSP 时须将匹配的软件包作为同一次事务安装；不要直接安装通用 `linux-aarch64` 来替换板级内核。

GPU 模块修订 `0.1.0_3-3` 使用官方的 XZ CRC32 校验与 1 MiB 字典。此前候选模块的 CRC64 校验触发 T5 模块解压器的 `status 6` 拒绝；已定位的问题是校验算法不兼容，不能把它归因于 8 MiB 字典。压缩格式修复与 [fdinfo 修复](gpu/kernel/README.md) 是两项独立检查；旧候选上的诊断和手动加载结果不计为最终镜像的首启、自动加载或升级后验收。

`radxa-a7z-base` 的 pacman hook 在 BSP 内核升级前保留旧内核、DTB、模块和 initramfs。升级后生成版本化启动文件，保留 extlinux 原默认入口。要明确切换内核才执行 `sudo a7z-boot-update --select`。

从 `radxa-a7z-base 0.1.0-3` 起，标准 mkinitcpio hook 输出到 `.img.pending`，项目 hook 另行生成 `.img.new`，成功后原子替换启动用的 `.img`。失败不应把原启动镜像截断。项目 hook 覆盖 mkinitcpio、systemd、固件和相关启动依赖文件更新。手工重建请使用：

```sh
sudo a7z-boot-update --initramfs
```

单独运行 `mkinitcpio -P` 只生成暂存输出，不完成这里的提交步骤。

T5 内核没有 Landlock。镜像只设置 `DisableSandboxFilesystem`，保留 pacman 下载用户权限隔离和系统调用过滤；日常升级不需要 `--disable-sandbox`。

## 历史测试：2026-09-14

| 测试 | 结果与范围 |
| --- | --- |
| 完整 `pacman -Syu` | 成功；测试时仓库与镜像包版本相同，没有待升级包，因此不能称为跨版本仓库升级 |
| 核心安装事务 | 完整 `-Syu` 同时重新安装 glibc、systemd、mkinitcpio、pacman、Mesa、libglvnd、libdrm、Xorg、NetworkManager、wpa_supplicant，共 10 包 |
| 驱动文件一致性 | 7,480 个内核模块、固件、专用 GPU 文件及启动相关文件的 SHA256 在核心事务前后相同 |
| 项目包实际版本升级 | base `0.1.0-2 → 0.1.0-3`，GPU 用户态 `24.2.6603887_t5-2 → -3`；不再安装未使用的私有 vendor Xorg/旧 OpenSSL 兼容包 |
| 新启动 hook 事务 | 再次完整 `-Syu` 重装 systemd/mkinitcpio，确认标准 hook 写 `.pending`，项目 hook 完成新镜像提交 |
| 失败模拟 | 模拟 mkinitcpio 部分写入后失败；原内核、initramfs、extlinux 不变，失败暂存文件移除 |
| 重启验证 | SD 启动 T5 `6.6.98-4-aw2511`，Wi-Fi/SSH 正常，无失败 systemd unit |
| 图形验证 | 原始核心事务后正常登录 XFCE、2560×1440 显示、Xorg PowerVR glamor；项目包升级重启后 EGL/GLES 单像素硬件绘制与 Vulkan 枚举再次通过 |
| 当日镜像首启更新 | CLI SD 与 KDE UFS 首启重新生成 pacman 本机密钥后，普通完整 `pacman -Syu` 均成功；当时仓库无待升级包。KDE 另完成实际签名包下载 |
| KDE Vulkan 图形包维护 | 完整 `-Syu` 同时重新安装 qt6-base、qt6-declarative、plasma-workspace、kwin-x11、Mesa、libglvnd、libdrm、SDDM，共 8 包；当时系统的 7,475 个驱动相关文件哈希不变 |
| KDE 维护后界面 | 重启 SDDM 后正常密码登录，登录界面与 Plasma 继续使用 PowerVR Vulkan，菜单启动 Dolphin/Konsole 正常；系统与用户服务均无失败项 |

测试版本：glibc `2.43+r22+g8362e8ce10b2-2`、systemd `261.3-1`、mkinitcpio `42-1`、pacman `7.1.0.r9.g54d9411-2`、Mesa `26.2.2-1`、libglvnd `1.7.0-3`、libdrm `2.4.134-1`、Xorg `21.1.24-1`、NetworkManager `1.58.1-1`、wpa_supplicant `2.12-1`。

KDE 新增测试版本为 Qt6 base `6.11.2-3`、Qt6 declarative `6.11.2-1`、Plasma workspace/KWin X11 `6.7.5-1`、SDDM `0.21.0-7`；8 包事务前后版本相同，是实际下载/签名检查/重装和 hook 测试，而非跨版本 Qt/KDE 升级。

这些结果限于当时的仓库快照和上述实际事务，不能保证未来任意 ABI 变化都与闭源 T5 用户态兼容。GLX 客户端走软件渲染；命令行 Vulkan 探针只涵盖设备枚举，KDE 另验证了 Qt Quick/SDDM/Plasma 的实际 Vulkan 界面呈现；未完成长时间压力测试。KDE 使用 Plasma X11，后续 Plasma 的 X11 生命周期变化需要单独适配，见 [KDE 说明](KDE.zh-CN.md)。

## 更新后的检查与恢复

### 2026-09-15 既有 KDE UFS 系统升级验证

在此前的 KDE UFS 验证系统上安装 `radxa-a7z-base 0.1.0-4`，实际完成 `0.1.0-3 → 0.1.0-4` 的项目包升级和启动 hook 执行。新版本修复 `sgdisk -e` 后 GPT 保留尾部间隙导致首次扩容失败的问题；实机根文件系统从约 7.3 GiB 扩至 117 GiB，保留分区起点和文件系统 UUID。另用 512/4096 字节扇区、是否预先运行 `sgdisk -e` 的四组真实 loop 磁盘测试检查内容、UUID、文件系统一致性及重复执行。

随后执行普通完整 `pacman -Syu`，当时仓库没有待升级包。7,508 个内核、固件、GPU/VPU 及启动相关文件的 SHA256 保持一致，系统和用户服务无失败项，PipeWire、PipeWire Pulse 与 WirePlumber 正常运行。Plasma 进程使用 `QSG_RHI_BACKEND=vulkan` 并加载私有 PowerVR Vulkan 库；KWin 保持软件回退与关闭合成的配置。

该轮使用 Chromium `153.0.8010.36-1`、Fcitx5 `5.1.22-1`、fcitx5-rime `5.1.16-1`、Qt6 base `6.11.2-3`、Qt6 declarative `6.11.2-2`、Plasma workspace/KWin X11 `6.7.5-1` 和 GStreamer `1.28.7-1`。KDE 内 Chromium 与 Kate 的实际键盘输入、简体中文候选及保存通过。Chromium 的 WebGL 1/2 像素绘制、浏览器沙箱检查、1080p30 H.264 短片播放通过；媒体日志明确为软件 `FFmpegVideoDecoder`。独立 GStreamer 的 Cedar H.264 解码显示 450 帧、零丢帧，并观察到 450 次硬件中断。

这些结果属于上述既有验证系统的项目包升级和仓库状态检查；不能替代后续候选镜像的升级后复测，也不保证未来版本兼容性。

### 历史候选镜像的升级测试（非本版最终验收）

2026-09-15，一份 KDE UFS 候选镜像首启后执行完整 `sudo pacman -Syu`，实际将 `libde265` 升级到 `1.1.3-1`，完成仓库同步、签名检查、安装和事务后 hook。此次跨版本升级仅涉及这个仓库包，不能表述为没有待升级包。

随后 KDE 登录、Chromium PowerVR WebGL 1/2 像素绘制，以及 Chromium/Kate 的实际 Rime 中文输入通过短测。浏览器 H.264 仍为软件 `FFmpegVideoDecoder`；独立 Cedar 管线的硬件中断增加 450，显示端为 448 帧、丢弃 2 帧，未通过严格零丢帧验收。

之后再次执行完整 `pacman -Syu`，没有新增待升级包，该次事务前后的 7,508 个驱动相关文件 SHA256 一致。这一比较发生在 `libde265` 升级之后，不能表述成该单包升级前后的哈希比较。浏览器的命名空间和 Seccomp-BPF/TSYNC 已启用，但 GPU 信息报告 `sandboxed=false`，因此没有据此认定 GPU 进程受沙箱保护。

该候选随后在重启期间因 PowerVR `pvr_show_fdinfo` 空指针触发 kernel panic，因此未通过发布验收。证据定位到旧 GPU 模块的信息查询路径，不能认定是 `libde265` 升级造成。此记录保留了实际升级范围，也说明短测和文件哈希不变不足以证明重启稳定性。

### 本版最终镜像的维护验证

本次发行构建复用构建机上经清理检查的同变体预制 rootfs，再按新配方执行完整 `pacman -Syu`、全部板级包的重新打包与安装、启动配置、清理和新镜像生成。输入不包含开发板上的系统或个人数据；没有重新解包 Arch 初始归档。审计后的 `build-manifest-*.json` 用 `input_reuse` 保存父构建相关哈希及实际重跑范围，用 `fresh_arch_seed_extracted=false` 明确记录复用方式。构建机上的更新事务不代替以下实机维护测试。

本版使用带 [fdinfo 修复](gpu/kernel/README.md) 的 `radxa-a7z-gpu-kmod 0.1.0_3-3`、GPU 用户态 `24.2.6603887_t5-7` 和 base `0.1.0-4`。本轮在 CLI SD、KDE UFS、XFCE SD 上记录完整 `pacman -Syu`、同版本重装项目、事务前后驱动文件哈希及随后的硬件复测；未启动的另外三个文件不借用这些结果。CLI 只测试其已安装包，不为维护测试安装图形组件；桌面版另执行 Mesa、libglvnd、libdrm 的完整更新/重装事务。测试时仓库均没有新版本，因此本轮证明的是完整更新流程和同版本重装后的回归，未模拟未来 ABI 变化。

CLI SD 最终文件（原始 SHA256 `535459d71badebf1e888b0a48daf334a7a895255c7aff6049fe31c918ee8ddcc`）在 2026-09-15 完成首启与完整 `pacman -Syu`。当时仓库无待升级包；事务前后 7,617 个 BSP、固件、GPU 和启动相关文件一致，生成的 initramfs 也未变化。随后普通重启通过，根 UUID 保持正确，Wi-Fi/SSH 正常、没有失败的系统服务，修复后的 GPU 模块再次自动加载。此项不包含图形桌面或跨版本升级。

KDE UFS 最终文件（原始 SHA256 `3a4f89cbdbe539f94cca7b0c61c1468e8d2873cea481c5a391778912520c9890`）同日执行完整 `pacman -Syu`，随后通过另一次完整 `-Syu` 重装 `libdrm 2.4.134-1`、`libglvnd 1.7.0-3` 和 `mesa 1:26.2.2-1`。没有包版本升级；两次事务前后 7,674 个 BSP 路径与生成的 initramfs 均保持不变。之后 PowerVR WebGL 1/2 实际像素绘制、Chromium 中输入「你好世界」、Kate 中文输入及保存、5 次 DRM fdinfo 查询及单个受控 SIGABRT 的 systemd-coredump 记录均通过。Chromium 和独立 Cedar/GStreamer 路径分别完成本地 450 帧 H.264 样片且未报告丢帧；前者仍是 `FFmpegVideoDecoder` 软件解码。实际空闲超过 16 分钟后可正常解锁，注销和重新登录通过；跟踪重启后再次确认 GPU 模块自动加载、网络正常、无失败系统服务，重新登录后的 PowerVR 绘制与 Rime 输入通过。此次 SD 卡保持插入，UFS 由串口临时选择，未计为拔卡冷启动测试。

XFCE SD 最终文件（原始 SHA256 `b39259448bf04d3c07d0d4af5817473363d9581491f3109ae119cec733a85b33`）同日完成完整 `pacman -Syu` 及另一次完整更新中的 Mesa、libglvnd、libdrm 同版本重装，版本与上面的 KDE 记录相同。两次事务前后 7,674 个 BSP 路径与生成的 initramfs 均保持一致。更新后 PowerVR WebGL 1/2、Chromium 与 Mousepad 中文输入、编辑器 UTF-8 保存及 5 次 fdinfo 查询通过；浏览器软件解码与独立 Cedar 硬解各完成 450 帧 H.264 样片且未报告丢帧。普通重启后根分区身份正确、GPU 模块自动加载、网络/SSH 正常且无失败系统服务，重新登录后 PowerVR 绘制和 Rime 中文输入再次通过。

### 历史 XFCE 增量记录与日常检查

2026-09-15 的 XFCE/Chromium/VPU 增量已另行完成当时完整 `-Syu` 依赖事务、
GPU 启动器包升级及 VPU 包安装验证，详见 [实机记录](gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md)。
它验证了当时 Chromium/GStreamer 与 T5 用户态配合，没有模拟未来版本兼容性。
使用新增浏览器入口时，更新后检查 `chrome://gpu` 的 PowerVR 渲染器和实际 WebGL
绘制；视频须检查媒体日志中的具体解码器，不能用流畅播放代替硬解证明。

```sh
uname -r
systemctl --failed
nmcli general status
a7z-gpu-run a7z-gpu-probe --api egl
a7z-gpu-run a7z-gpu-probe --api vulkan
```

更新前保留可启动的 SD 卡和自己的配置/数据备份。启动文件备份并不是整个用户态系统的快照；若升级涉及图形库或大量核心包，完整恢复需要自己的系统备份。备份可能含 Wi-Fi 密码与 SSH 私钥，不能随公开发布物上传。
