# 日常维护与滚动升级

日常更新使用完整事务：

```sh
sudo pacman -Syu
sudo reboot
```

按照 [Arch 系统维护说明](https://wiki.archlinux.org/title/System_maintenance)，不要使用 `pacman -Sy` 后仅更新个别软件包的部分升级方式。普通 Arch Linux ARM 软件来自其仓库；板级内核、无线模块、GPU 模块与专用用户态来自本项目的 T5 软件包。没有用宽泛的 `IgnorePkg` 冻结整个系统，也没有替换 Arch 的 Mesa、libglvnd 或系统 Xorg。

## 驱动与启动文件的保护

板级内核与外部模块采用匹配的 T5 版本，GPU 用户态依赖对应的 GPU 模块。更换 BSP 时须将匹配的软件包作为同一次事务安装；不要直接安装通用 `linux-aarch64` 来替换板级内核。

`radxa-a7z-base` 的 pacman hook 在 BSP 内核升级前保留旧内核、DTB、模块和 initramfs。升级后生成版本化启动文件，保留 extlinux 原默认入口。要明确切换内核才执行 `sudo a7z-boot-update --select`。

从 `radxa-a7z-base 0.1.0-3` 起，标准 mkinitcpio hook 输出到 `.img.pending`，项目 hook 另行生成 `.img.new`，成功后原子替换启动用的 `.img`。失败不应把原启动镜像截断。项目 hook 覆盖 mkinitcpio、systemd、固件和相关启动依赖文件更新。手工重建请使用：

```sh
sudo a7z-boot-update --initramfs
```

单独运行 `mkinitcpio -P` 只生成暂存输出，不完成这里的提交步骤。

T5 内核没有 Landlock。镜像只设置 `DisableSandboxFilesystem`，保留 pacman 下载用户权限隔离和系统调用过滤；日常升级不需要 `--disable-sandbox`。

## 2026-09-14 实机测试

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
| 新镜像首启更新 | CLI SD 与 KDE UFS 首启重新生成 pacman 本机密钥后，普通完整 `pacman -Syu` 均成功；仓库无待升级包。KDE 另完成实际签名包下载 |
| KDE Vulkan 图形包维护 | 完整 `-Syu` 同时重新安装 qt6-base、qt6-declarative、plasma-workspace、kwin-x11、Mesa、libglvnd、libdrm、SDDM，共 8 包；当前系统 7,475 个驱动相关文件哈希不变 |
| KDE 维护后界面 | 重启 SDDM 后正常密码登录，登录界面与 Plasma 继续使用 PowerVR Vulkan，菜单启动 Dolphin/Konsole 正常；系统与用户服务均无失败项 |

测试版本：glibc `2.43+r22+g8362e8ce10b2-2`、systemd `261.3-1`、mkinitcpio `42-1`、pacman `7.1.0.r9.g54d9411-2`、Mesa `26.2.2-1`、libglvnd `1.7.0-3`、libdrm `2.4.134-1`、Xorg `21.1.24-1`、NetworkManager `1.58.1-1`、wpa_supplicant `2.12-1`。

KDE 新增测试版本为 Qt6 base `6.11.2-3`、Qt6 declarative `6.11.2-1`、Plasma workspace/KWin X11 `6.7.5-1`、SDDM `0.21.0-7`；8 包事务前后版本相同，是实际下载/签名检查/重装和 hook 测试，而非跨版本 Qt/KDE 升级。

这些结果证明当前仓库快照和上述实际事务可用，不能保证未来任意 ABI 变化都与闭源 T5 用户态兼容。GLX 客户端走软件渲染；命令行 Vulkan 探针只涵盖设备枚举，KDE 另验证了 Qt Quick/SDDM/Plasma 的实际 Vulkan 界面呈现；未完成长时间压力测试。KDE 使用 Plasma X11，后续 Plasma 的 X11 生命周期变化需要单独适配，见 [KDE 说明](KDE.zh-CN.md)。

## 更新后的检查与恢复

2026-09-15 的 XFCE/Chromium/VPU 增量已另行完成当前完整 `-Syu` 依赖事务、
GPU 启动器包升级及 VPU 包安装验证，详见 [实机记录](gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md)。
它验证了当前 Chromium/GStreamer 与 T5 用户态配合，没有模拟未来版本兼容性。
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
