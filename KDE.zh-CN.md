# KDE 中文桌面、Chromium 与 T5 图形边界

本项目提供三个独立构建变体：`cli` 使用命令行和网络管理工具，`xfce` 使用 XFCE + LightDM，`kde` 使用 Plasma X11 + SDDM。常规构建从锁定的 Arch Linux ARM seed 独立解包；v0.2.2 补丁发行复用构建机上同变体的干净离线 rootfs 和既有包快照，安装新内核及配套板级包后重新生成镜像，没有执行 `pacman -Syu`。三个变体不混用已安装其他桌面的根文件系统，也不从测试板导出用户系统。

`v0.2.0-t5` 的 KDE 配方与 XFCE 一样预装 **Chromium（PowerVR）** 和 **Fcitx5 + Rime**，设置中文会话、字体与默认网页关联。桌面沿用此前实测的 SDDM/Plasma PowerVR Vulkan 配置；KWin 窗口合成保持关闭。网页 GPU 绘制和 Chromium 视频硬解是两项能力，后者仍未接通，不能把桌面配置的改进理解为浏览器视频已硬解。

`v0.2.2-t5` 加入与 CLI / XFCE 相同的 HDMI 内核补丁，移除 SDDM 的旧 `95-a7z-hdmi-compat.conf` 钩子；保留 `70-a7z-desktop.conf`、PowerVR Vulkan 和原系统 Xsetup / Xstop。HDMI 不再依赖启动脚本强制 HPD。此前只在 CLI 确认了两次启动与一次同屏拔插，本次 KDE 新包和 SD / UFS 镜像没有新增测试。HDCP、换显示器和休眠恢复边界见 [HDMI 说明](desktop/HDMI.zh-CN.md)，本次范围见 [发行说明](RELEASE.zh-CN.md)。

## 当前上游与选择

Arch Linux ARM 提供 aarch64 的 [plasma-x11-session](https://archlinuxarm.org/packages/aarch64/plasma-x11-session)、[kwin-x11](https://archlinuxarm.org/packages/aarch64/kwin-x11) 和 [SDDM](https://archlinuxarm.org/packages/aarch64/sddm)。此前 T5 实测使用 Plasma X11 / KWin X11 6.7.5-1、SDDM 0.21.0-7；每次构建记录实际安装版本，当前仓库页面不代表旧镜像的包版本。

Arch 已将 X11 会话改为需要显式安装的包；只安装 Plasma 默认包集不足以保证能登录 X11。[Arch 官方说明](https://archlinux.org/news/plasma-640-will-need-manual-intervention-if-you-are-on-x11/)。当前 `plasma-meta` 还引入 `plasma-login-manager`，本板采用明确的组件包集以选择 SDDM。

KDE 已宣布 Plasma 6.8 移除完整 X11 登录会话，6.7 的 X11 维护计划延续到 2027 年初；这是一条有期限的兼容路线。[KDE Plasma 团队公告](https://blogs.kde.org/2025/11/26/going-all-in-on-a-wayland-future/)。构建发现 `startplasma-x11` 会话文件缺失时会停止，不能静默切为未经本板验收的 Wayland。长期继续升级 KDE 需要先解决/验收 T5 GPU 的 Wayland 路径，单独冻结零散 Plasma 包不能保证 Arch 滚动依赖一致性。

## 软件包和显示服务

| 变体 | 桌面/服务与额外包 |
|---|---|
| cli | 不安装 Xorg server、显示管理器或桌面环境，默认 multi-user.target；保留 SSH、NetworkManager、蓝牙命令行、BSP 维护和私有 GPU 必需库、Vulkan 诊断工具 |
| xfce | Arch Xorg + XFCE + LightDM；Chromium（PowerVR）、Fcitx5 + Rime、NetworkManager 托盘与中文字体，默认 graphical.target |
| kde | Arch Xorg + plasma-desktop + plasma-x11-session + SDDM；Chromium（PowerVR）、Fcitx5 + Rime、plasma-nm、plasma-pa、kscreen、Dolphin、Konsole、Kate、Ark、PipeWire/WirePlumber、KDE portal 和中文字体，默认 graphical.target |

KDE 软件包的依赖可能同时包含 KWin Wayland 和 Wayland 库；这不表示镜像启用了 Wayland 会话。SDDM 配置把 Wayland 会话目录指向专用空目录，X11 会话目录保留 `/usr/share/xsessions`。没有删除或改写 Arch 提供的 session 文件，没有开启自动登录。

`rootfs.py bootstrap/finalize --variant cli|xfce|kde` 明确选择变体。旧的 `--desktop` 等价于 `--variant xfce`，同时传入其他变体会被拒绝。不指定时 `rootfs.py` 保持默认 CLI；顶层 `build.py` 的默认变体仍由其自身选项决定。构建器检查变体标记和已安装桌面包，拒绝把含其他桌面的 rootfs 用作目标变体。

## 空闲与电源策略

KDE 镜像默认关闭交流供电（AC）时的自动休眠，让开发板在桌面闲置时保持运行。配置位于 `/etc/xdg/powerdevilrc`：

```ini
[AC][SuspendAndShutdown]
AutoSuspendAction=0
```

这是可被用户设置覆盖的默认值；可在 KDE“系统设置 → 电源管理”中重新配置自动休眠。它不改变显示器熄屏、锁屏、按键动作或手动休眠，也没有通过 systemd 禁用休眠能力。`AutoSuspendAction=0` 表示不注册空闲休眠动作，配置文件及分组来自 [PowerDevil 6.7.5 配置定义](https://github.com/KDE/powerdevil/blob/v6.7.5/PowerDevilProfileSettings.kcfg)，行为由 [SuspendSession 实现](https://github.com/KDE/powerdevil/blob/v6.7.5/daemon/actions/bundled/suspendsession.cpp) 定义。

PowerDevil 上游在系统报告支持休眠且并非虚拟机时，默认 AC 空闲 900 秒后请求休眠。[上游默认值](https://github.com/KDE/powerdevil/blob/v6.7.5/daemon/powerdevilsettingsdefaults.cpp)。本版关闭这一默认动作以保持无人值守时的网络连接。手动休眠及其后的唤醒恢复仍未通过本项目实机验证；这项策略只用于 KDE 镜像，不改变 CLI 或 XFCE 的电源设置。

## KDE 初始图形配置

默认 `a7z-gpu-desktop enable arch-glamor --display-manager sddm` 只给 Arch Xorg 选择 T5 私有 EGL/GBM，使用稳定的 sunxi-drm KMS 路径并关闭 AutoAddGPU。SDDM 的 `DisplayServer=x11`、`ServerPath`、`SessionDir` 是上游配置项。[SDDM 0.21 手册](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/data/man/sddm.conf.rst.in)。`GreeterEnvironment` 仅作用于 greeter，KDE 镜像在独立配置中用它选择 Vulkan。[SDDM 配置源码](https://raw.githubusercontent.com/sddm/sddm/v0.21.0/src/common/Configuration.h)。

KDE 镜像使用以下配置：

- `/etc/xdg/kwinrc` 的 `[Compositing] Enabled=false`：禁用 KWin X11 合成；配置键由 [KWin 6.7.5 源码](https://raw.githubusercontent.com/KDE/kwin-x11/v6.7.5/src/kwin.kcfg) 定义。
- `/etc/xdg/plasma-workspace/env/a7z-t5.sh`：保留会话软件默认值 `QT_QUICK_BACKEND=software` 与 `LIBGL_ALWAYS_SOFTWARE=1`，用于其他应用和回退；该目录由 [Plasma 启动代码](https://raw.githubusercontent.com/KDE/plasma-workspace/v6.7.5/startkde/startplasma.cpp) 读取。
- `/etc/sddm.conf.d/80-a7z-kde-greeter.conf`：保留 `LIBGL_ALWAYS_SOFTWARE=1,QSG_RHI_BACKEND=opengl`，作为 Breeze 登录主题的 Mesa llvmpipe 回退。它在 helper 的 `70-a7z-desktop.conf` 之后读取。
- `/etc/sddm.conf.d/90-a7z-kde-vulkan.conf`：默认覆盖 greeter 环境，设置 `QSG_RHI_BACKEND=vulkan` 与 `VK_DRIVER_FILES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json`。
- `/etc/systemd/user/plasma-plasmashell.service.d/90-a7z-kde-vulkan.conf`：仅对 Plasma shell 清除软件强制项及私有库搜索环境，设置相同的 Vulkan 后端和 ICD。保留上游服务的 `ExecStart`、D-Bus 名称和会话生命周期，配置在注销后仍有效。

Qt Quick 支持通过 `QSG_RHI_BACKEND` 选择 Vulkan 或 OpenGL。[Qt 渲染器文档](https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph-renderer.html)。此前图形适配测试在本板创建了 PowerVR Vulkan XCB 窗口交换链并显示动态画面；当时 SDDM 和 Plasma 的硬件渲染由进程环境、实际库映射、渲染器日志和截图共同验证。T5 Vulkan ICD 自带相对运行库搜索路径，因此这里不需要私有 EGL/GBM 环境或 Qt 注入库。

没有全局 `LD_LIBRARY_PATH`、`LD_PRELOAD`、Mesa/libglvnd 替换或整会话私有 GPU 库 wrapper。菜单启动程序可能继承 Plasma 的 `QSG_RHI_BACKEND` 和 `VK_DRIVER_FILES`；此前图形适配测试中的 Dolphin、Konsole 同时保留用户服务管理器的软件默认值，实际使用 Arch 库且没有加载私有 EGL/GBM。单个应用的实际后端须分别检查，不能认为所有应用均改用 GPU。显式 `a7z-gpu-run PROGRAM` 仍供 EGL/GLES/Vulkan 探针使用。

KWin X11 的 EGL/GLES 合成实验在创建窗口 surface 的 DRI 回调路径崩溃；设置 GLES 默认格式仍不能修复，具体驱动交互原因未定。因此不启用 KWin 合成和依赖合成的桌面特效。GLX 仍为软件兼容路径，不能用 Xorg glamor 或 Plasma Vulkan 的成功推断 GLX 加速。

## 预装 Chromium 与中文输入

KDE 和 XFCE 共用 GPU 包中的 `a7z-chromium`，默认网页关联为 `a7z-chromium.desktop`。菜单选择 **Chromium（PowerVR）**，或在终端运行：

```sh
a7z-chromium
```

启动器使用 Arch Chromium，选择 X11、ANGLE Vulkan 和私有 PowerVR ICD；不向浏览器注入私有 EGL/GBM 库，不关闭沙箱，不替换 Mesa/GLVND。它使用用户自己的标准 Chromium profile，保留原浏览器菜单项和软件回退。具体参数、用户 flags 冲突处理和检查步骤见 [Chromium 文档](gpu/CHROMIUM.zh-CN.md)。更换后端前应正常退出所有浏览器实例；同一 profile 的现有浏览器进程会接管后续启动。

`chrome://gpu` 用来检查 Compositing、Canvas、Rasterization、WebGL/WebGL2 的实际状态。网页用 GPU 绘制后，视频仍可由 CPU 解码；已有 Chromium 媒体日志报告 `FFmpegVideoDecoder`，本版没有新增浏览器视频解码接口。KDE/XFCE 另预装 GStreamer 和 `radxa-a7z-vpu`，通过 `a7z-vpu-run` 为独立应用选择 Cedar/OMX H.264 硬解后端；CLI 不安装这个 VPU 包。视频检查须区分解码器、硬件中断与显示端丢帧，不能只凭播放流畅判断。缺少的 Chromium 接口和后续路线见 [视频适配说明](vpu/CHROMIUM-INTEGRATION.zh-CN.md)；两种桌面的实际性能分别记录。

中文输入使用官方仓库的 `fcitx5`、`fcitx5-rime`、`fcitx5-gtk`、`fcitx5-qt`、`fcitx5-configtool` 和 `rime-luna-pinyin`。默认方案为「朙月拼音·简化字」，初始英文，`Ctrl+Space` 切换中英文；输入拼音后按空格选择候选。Rime 会在首次启用时部署，用户可在 Fcitx5 配置工具中修改热键和输入法。

`zh_CN.UTF-8` 与 GTK/Qt/XIM 输入法变量只用于 X11 图形会话，不改变串口或 TTY 的语言。KDE 使用 `.config/plasma-workspace/env/70-a7z-chinese.sh` 补充会话入口，Fcitx5 自动启动沿用官方 desktop 文件。预设写入 `/etc/skel` 后由镜像清理流程建立干净 home，不附带旧用户词库、部署缓存或浏览器数据。完整说明见 [中文桌面预设](desktop/README.zh-CN.md)，具体文件由 [tools/desktop.py](tools/desktop.py) 生成。

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

## 构建与验收范围

顶层使用不同工作目录：

```sh
python3 tools/build.py --variant cli --work-dir /root/a7z-archlinux-work/build-cli --hdmi-kernel-input /path/to/hdmi-kernel-input
python3 tools/build.py --variant kde --work-dir /root/a7z-archlinux-work/build-kde --hdmi-kernel-input /path/to/hdmi-kernel-input
```

CLI 的 GPU 包步骤使用 `package_gpu.py --components userspace --strict --target-root ROOT ...`，只打包和检查实际安装的私有用户态，不为可选 vendor Xorg 引入整套额外依赖。默认 `--components all` 保留原三包输出用于对照。不同组件审计的报告明确记录 `audited_components`，不能把仅用户态的通过当成可选 vendor Xorg 也已验证。

本版使用 HDMI 内核包 `6.6.98_4-2`、`radxa-a7z-gpu-kmod 0.1.0_3-4`、GPU 用户态包 `24.2.6603887_t5-8` 和 base `0.1.0-6`。GPU 包修订用于匹配依赖，沿用已有 [fdinfo 修复](gpu/kernel/README.md)。本次未运行桌面或滚动升级测试，未改变 KWin 合成或 Chromium 视频解码的边界。

### 历史记录：v0.2.0-t5

2026-09-15，v0.2.0 最终 KDE UFS 镜像完成整盘写后回读、首次启动和扩容、Wi-Fi 联网、SDDM 正常登录、完整更新及 Mesa/libglvnd/libdrm 重装。更新后 Chromium 的 PowerVR WebGL 1/2 像素绘制与 Rime 输入「你好世界」、Kate 中文输入及保存均通过。Plasma 映射私有 PowerVR Vulkan 库，Xorg 使用 PowerVR glamor；KWin 保持软件回退且关闭合成。

实际输入空闲 982,162 ms 后，PowerDevil 仍在 AC 模式，自动休眠动作值为 0，网络可用；随后密码解锁、正常注销和重新登录通过。跟踪重启后，根分区、板级包与自动加载的 GPU 模块身份正确，系统无失败服务；再次登录后的 Chromium 绘制及中文输入也通过。本轮 UFS 启动由串口临时选择，SD 卡保持插入，未把它计为拔卡后的独立冷启动或休眠恢复测试。

浏览器与独立 GStreamer 分别播放本地 15 秒、450 帧的 H.264 1080p30 样片，均未报告丢帧。Chromium 使用 `FFmpegVideoDecoder` 软件解码；独立 OMX 路径的 Cedar 中断增加 450。后者协商为 SystemMemory YV12 1920×1088，本次未验证裁剪元数据、音频输出或零拷贝。浏览器命名空间和 Seccomp-BPF/TSYNC 已启用，但 GPU 信息中的 `sandboxed=false`，不能据此认定 GPU 进程受沙箱保护。

上述历史结果及图形包更新事务保留在 [滚动升级说明](ROLLING-UPGRADE.zh-CN.md)，用于限定已测版本和范围；它们不代替 v0.2.2 新镜像验收，也不保证未来 Qt、Plasma 或 Chromium 的兼容性。
