# KDE / CLI 变体与 T5 图形边界

本项目新增两个独立构建变体：`cli` 使用命令行和网络管理工具，`kde` 使用 Plasma X11 + SDDM。它们均从锁定的 Arch Linux ARM seed 独立解包，不能从已装 XFCE 的根文件系统改名生成。原 `xfce` 仍使用 XFCE + LightDM。2026-09-14 的 KDE/SDDM 初版处于构建验证阶段，不能把已通过的 XFCE 实机结果当成 KDE 已通过。

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

默认 `a7z-gpu-desktop enable arch-glamor --display-manager sddm` 只给 Arch Xorg 选择 T5 私有 EGL/GBM，使用稳定的 sunxi-drm KMS 路径并关闭 AutoAddGPU。SDDM 的 `DisplayServer=x11`、`ServerPath`、`SessionDir` 是上游配置项。[SDDM 0.21 手册](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/data/man/sddm.conf.rst.in)。它的 `GreeterEnvironment` 项用于仅给 greeter 选择软件渲染。[SDDM 配置源码](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/src/common/Configuration.h)。

Plasma 使用以下兼容默认值：

- `/etc/xdg/kwinrc` 的 `[Compositing] Enabled=false`：禁用 KWin X11 合成；配置键由 [KWin 6.7.5 源码](https://raw.githubusercontent.com/KDE/kwin-x11/v6.7.5/src/kwin.kcfg) 定义。
- `/etc/xdg/plasma-workspace/env/a7z-t5.sh`：仅在 Plasma 会话设置 `QT_QUICK_BACKEND=software` 与 `LIBGL_ALWAYS_SOFTWARE=1`；该目录由 [Plasma 启动代码](https://raw.githubusercontent.com/KDE/plasma-workspace/v6.7.5/startkde/startplasma.cpp) 读取。
- SDDM greeter 单独设置同样的软件渲染选择。

Qt Quick 的 software 后端由 Qt 官方支持，它不要求为场景图创建硬件 3D 上下文，但效果和性能与默认硬件后端不同。[Qt 官方文档](https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations.html)。这些默认值避免依赖本板尚未证明可用的 GLX 客户端加速；X server 的 PowerVR glamor 与 Plasma 客户端的软件渲染是不同层次。

没有全局 `LD_LIBRARY_PATH`、Mesa/libglvnd 替换或整会话私有 GPU 库 wrapper。普通 Plasma 应用继续使用 Arch 库。显式 `a7z-gpu-run PROGRAM` 会清除 `LIBGL_ALWAYS_SOFTWARE`，所以 EGL/GLES/Vulkan 工具仍能选择 T5 GPU；它不会自动把任意 Qt Quick 程序切回已验收的硬件渲染。

软件显示回退命令：

```sh
sudo a7z-gpu-desktop enable arch-software --display-manager sddm
```

保存图形会话工作后可在文本终端/SSH 执行 `sudo systemctl restart sddm` 应用配置；这会结束图形会话。恢复 Xorg glamor 用相同命令改成 `arch-glamor`。这个回退不移除 KMS 指定，也不自动改变 Plasma 合成设置。

## 构建与验收

顶层使用不同工作目录：

```sh
python3 tools/build.py --variant cli --work-dir /root/a7z-archlinux-work/build-cli
python3 tools/build.py --variant kde --work-dir /root/a7z-archlinux-work/build-kde
```

CLI 的 GPU 包步骤使用 `package_gpu.py --components userspace --strict --target-root ROOT ...`，只打包和检查实际安装的私有用户态，不为可选 vendor Xorg 引入整套额外依赖。默认 `--components all` 保留原三包输出用于对照。不同组件审计的报告明确记录 `audited_components`，不能把仅用户态的通过当成可选 vendor Xorg 也已验证。

KDE 的独立 rootfs 已完成 bootstrap、七个板级包安装及 finalize，共 639 个包、约 4.8 GiB；Plasma/X11/KWin 6.7.5-1、SDDM 0.21.0-7、base 0.1.0-3 与 GPU userspace 修订 3 均安装到位。SDDM 配置解析和用户态静态依赖检查通过，没有残留 XFCE/LightDM 包、chroot 进程或绑定挂载。后续为公共镜像清理、生成两种扇区镜像及实机启动验证。

KDE 实机必须分别确认 SDDM greeter、正常密码登录、Plasma panel/桌面、网络管理、注销再登录、Xorg glamor、会话软件渲染环境和普通用户 EGL 探针。尚未完成前，KDE 镜像应明确标为待验收。GPU 已知 GLX/Vulkan 范围见 [发行说明](RELEASE.zh-CN.md)。
