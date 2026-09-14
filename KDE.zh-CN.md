# KDE / CLI 变体与 T5 图形边界

本项目提供三个独立构建变体：`cli` 使用命令行和网络管理工具，`xfce` 使用 XFCE + LightDM，`kde` 使用 Plasma X11 + SDDM。它们均从锁定的 Arch Linux ARM seed 独立解包，不能从已装其他桌面的根文件系统改名生成。2026-09-14 的 KDE UFS 实机已验证 PowerVR Vulkan 渲染 SDDM 登录界面和 Plasma 面板、菜单，并完成正常密码登录、注销重登和常用应用测试。KWin 窗口合成保持关闭。

## 当前上游与选择

Arch Linux ARM 当前仍提供 aarch64 的 [plasma-x11-session](https://archlinuxarm.org/packages/aarch64/plasma-x11-session)、[kwin-x11](https://archlinuxarm.org/packages/aarch64/kwin-x11) 和 [SDDM](https://archlinuxarm.org/packages/aarch64/sddm)。本次同步仓库实际查询为 Plasma X11 / KWin X11 6.7.5-1、SDDM 0.21.0-7，构建会记录最后安装版本。

Arch 已将 X11 会话改为需要显式安装的包；只安装 Plasma 默认包集不足以保证能登录 X11。[Arch 官方说明](https://archlinux.org/news/plasma-640-will-need-manual-intervention-if-you-are-on-x11/)。当前 `plasma-meta` 还引入 `plasma-login-manager`，本板采用明确的组件包集以选择 SDDM。

KDE 已宣布 Plasma 6.8 移除完整 X11 登录会话，6.7 的 X11 维护计划延续到 2027 年初；这是一条有期限的兼容路线。[KDE Plasma 团队公告](https://blogs.kde.org/2025/11/26/going-all-in-on-a-wayland-future/)。构建发现 `startplasma-x11` 会话文件缺失时会停止，不能静默切为未经本板验收的 Wayland。长期继续升级 KDE 需要先解决/验收 T5 GPU 的 Wayland 路径，单独冻结零散 Plasma 包不能保证 Arch 滚动依赖一致性。

## 软件包和显示服务

| 变体 | 桌面/服务与额外包 |
|---|---|
| cli | 不安装 Xorg server、显示管理器或桌面环境，默认 multi-user.target；保留 SSH、NetworkManager、蓝牙命令行、BSP 维护和私有 GPU 必需库、Vulkan 诊断工具 |
| xfce | Arch Xorg + XFCE + LightDM，NetworkManager 托盘与字体，默认 graphical.target |
| kde | Arch Xorg + plasma-desktop + plasma-x11-session + SDDM；plasma-nm、plasma-pa、kscreen、Dolphin、Konsole、Kate、Ark、PipeWire/WirePlumber、KDE portal 和字体，默认 graphical.target |

KDE 软件包的依赖可能同时包含 KWin Wayland 和 Wayland 库；这不表示镜像启用了 Wayland 会话。SDDM 配置把 Wayland 会话目录指向专用空目录，X11 会话目录保留 `/usr/share/xsessions`。没有删除或改写 Arch 提供的 session 文件，没有开启自动登录。

`rootfs.py bootstrap/finalize --variant cli|xfce|kde` 明确选择变体。旧的 `--desktop` 等价于 `--variant xfce`，同时传入其他变体会被拒绝。不指定时 `rootfs.py` 保持默认 CLI；顶层 `build.py` 的默认变体仍由其自身选项决定。构建器检查变体标记和已安装桌面包，拒绝把含其他桌面的 rootfs 用作目标变体。

## KDE 初始图形配置

默认 `a7z-gpu-desktop enable arch-glamor --display-manager sddm` 只给 Arch Xorg 选择 T5 私有 EGL/GBM，使用稳定的 sunxi-drm KMS 路径并关闭 AutoAddGPU。SDDM 的 `DisplayServer=x11`、`ServerPath`、`SessionDir` 是上游配置项。[SDDM 0.21 手册](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/data/man/sddm.conf.rst.in)。`GreeterEnvironment` 仅作用于 greeter，KDE 镜像在独立配置中用它选择 Vulkan。[SDDM 配置源码](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/src/common/Configuration.h)。

KDE 镜像使用以下配置：

- `/etc/xdg/kwinrc` 的 `[Compositing] Enabled=false`：禁用 KWin X11 合成；配置键由 [KWin 6.7.5 源码](https://raw.githubusercontent.com/KDE/kwin-x11/v6.7.5/src/kwin.kcfg) 定义。
- `/etc/xdg/plasma-workspace/env/a7z-t5.sh`：保留会话软件默认值 `QT_QUICK_BACKEND=software` 与 `LIBGL_ALWAYS_SOFTWARE=1`，用于其他应用和回退；该目录由 [Plasma 启动代码](https://raw.githubusercontent.com/KDE/plasma-workspace/v6.7.5/startkde/startplasma.cpp) 读取。
- `/etc/sddm.conf.d/80-a7z-kde-greeter.conf`：保留 `LIBGL_ALWAYS_SOFTWARE=1,QSG_RHI_BACKEND=opengl`，作为 Breeze 登录主题的 Mesa llvmpipe 回退。它在 helper 的 `70-a7z-desktop.conf` 之后读取。
- `/etc/sddm.conf.d/90-a7z-kde-vulkan.conf`：默认覆盖 greeter 环境，设置 `QSG_RHI_BACKEND=vulkan` 与 `VK_DRIVER_FILES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json`。
- `/etc/systemd/user/plasma-plasmashell.service.d/90-a7z-kde-vulkan.conf`：仅对 Plasma shell 清除软件强制项及私有库搜索环境，设置相同的 Vulkan 后端和 ICD。保留上游服务的 `ExecStart`、D-Bus 名称和会话生命周期，配置在注销后仍有效。

Qt Quick 支持通过 `QSG_RHI_BACKEND` 选择 Vulkan 或 OpenGL。[Qt 渲染器文档](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph-renderer.html)。本板实际创建了 PowerVR Vulkan XCB 窗口交换链并显示动态画面；SDDM 和 Plasma 的硬件渲染由进程环境、实际库映射、渲染器日志和截图共同验证。T5 Vulkan ICD 自带相对运行库搜索路径，因此这里不需要私有 EGL/GBM 环境或 Qt 注入库。

没有全局 `LD_LIBRARY_PATH`、`LD_PRELOAD`、Mesa/libglvnd 替换或整会话私有 GPU 库 wrapper。菜单启动程序可能继承 Plasma 的 `QSG_RHI_BACKEND` 和 `VK_DRIVER_FILES`；本次 Dolphin、Konsole 同时保留用户服务管理器的软件默认值，实际使用 Arch 库且没有加载私有 EGL/GBM。它们能正常使用，不代表所有应用均改用 GPU。显式 `a7z-gpu-run PROGRAM` 仍供 EGL/GLES/Vulkan 探针使用。

KWin X11 的 EGL/GLES 合成实验在创建窗口 surface 的 DRI 回调路径崩溃；设置 GLES 默认格式仍不能修复，具体驱动交互原因未定。因此不启用 KWin 合成和依赖合成的桌面特效。GLX 仍为软件兼容路径，不能用 Xorg glamor 或 Plasma Vulkan 的成功推断 GLX 加速。

## 回退与恢复

需要回退 Qt 界面时，先保存工作，然后从文本终端或 SSH 暂停两个硬件覆盖文件：

```sh
sudo mv -i /etc/sddm.conf.d/90-a7z-kde-vulkan.conf /etc/sddm.conf.d/90-a7z-kde-vulkan.conf.disabled
sudo mv -i /etc/systemd/user/plasma-plasmashell.service.d/90-a7z-kde-vulkan.conf /etc/systemd/user/plasma-plasmashell.service.d/90-a7z-kde-vulkan.conf.disabled
systemctl --user daemon-reload
sudo systemctl restart sddm
```

最后一条会结束当前图形会话。下一次登录使用保留的 Plasma 软件后端和 SDDM CPU OpenGL；Breeze 的部分效果在 Qt QPainter 软件后端不可用，因此 greeter 的回退是 llvmpipe OpenGL。[Qt 软件后端限制](https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations.html)。恢复硬件时，将两个 `.conf.disabled` 文件移回原来的 `.conf` 文件名，再重新加载用户服务并重启 SDDM。

如果还需要回退 X server 本身的加速，再执行：

```sh
sudo a7z-gpu-desktop enable arch-software --display-manager sddm
```

随后重启 SDDM 应用设置。恢复 Xorg glamor 用相同命令改成 `arch-glamor`。这个命令只改变 X server 配置，保留 KMS 指定；它不会停用上面的 Vulkan 覆盖或改变 KWin 合成设置。

## 构建与验收

顶层使用不同工作目录：

```sh
python3 tools/build.py --variant cli --work-dir /root/a7z-archlinux-work/build-cli
python3 tools/build.py --variant kde --work-dir /root/a7z-archlinux-work/build-kde
```

CLI 的 GPU 包步骤使用 `package_gpu.py --components userspace --strict --target-root ROOT ...`，只打包和检查实际安装的私有用户态，不为可选 vendor Xorg 引入整套额外依赖。默认 `--components all` 保留原三包输出用于对照。不同组件审计的报告明确记录 `audited_components`，不能把仅用户态的通过当成可选 vendor Xorg 也已验证。

KDE 的独立 rootfs 完成 bootstrap、七个板级包安装及 finalize，共 639 个包、约 4.8 GiB；Plasma/X11/KWin 6.7.5-1、SDDM 0.21.0-7、base 0.1.0-3 与 GPU userspace 修订 3 均安装到位。没有残留 XFCE/LightDM 包。Vulkan 界面配置只增加 KDE 的 rootfs 配置，不修改 Arch 包或板级 GPU 包。

KDE UFS 实机已确认 2560×1440 显示、SDDM 密码认证及注销重登、PowerVR Vulkan Plasma 面板与应用菜单、菜单启动的 Konsole 和 Dolphin、PowerVR Xorg glamor，以及关闭的 KWin 合成。Arch 的 EGL/GLX 库保留完整，私有 Vulkan 实现通过 ICD 加载。Xorg、Mesa、libglvnd、Plasma、KWin 和 SDDM 的包文件完整性检查通过。当前鼠标指针可出现方形背景，已测试交互仍可用。GPU 已知范围见 [发行说明](RELEASE.zh-CN.md)。此验收不代表所有 KDE 应用、Wayland、桌面特效或硬件视频解码均已验证。

Vulkan 配置还完成了一次完整 `pacman -Syu` 事务，并重装当前版本的 Qt base/declarative、Plasma workspace、KWin X11、Mesa、libglvnd、libdrm 和 SDDM。7,475 个驱动文件的 SHA-256 全部不变。随后重启 SDDM、正常密码登录并重新从菜单打开两款应用，硬件 Plasma 和库隔离仍正常，系统与用户均无 failed units。这验证了本次完整事务及同版本重装，不构成对未来任意版本升级的保证。
