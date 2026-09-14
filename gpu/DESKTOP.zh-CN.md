# Arch Xorg 与 T5 GPU 桌面配置

A7Z 的显示控制器与渲染 GPU 分离。Arch `modesetting` 必须使用稳定的显示节点 `/dev/dri/by-path/platform-soc@3000000:sunxi-drm-card`，并关闭 `AutoAddGPU`，避免把没有显示扫描输出的 GPU 节点选作主显示设备。

`a7z-gpu-desktop` 管理一个专属 Xorg 片段，以及所选显示管理器的专属片段。它允许更新带管理标记的旧配置，拒绝覆盖同名非受管文件；不会替换 Arch 软件包文件、启用服务、自动登录或重启显示服务。

## LightDM / XFCE

不指定显示管理器时默认使用 LightDM：

```sh
# 预览配置。
a7z-gpu-desktop print arch-glamor
# 为 Arch X server 选择 T5 私有 EGL/GBM，下次显示服务启动生效。
sudo a7z-gpu-desktop enable arch-glamor
# 软件显示回退，仍保留正确 KMS 选择。
sudo a7z-gpu-desktop enable arch-software
```

`arch-glamor` 使用 `/usr/lib/radxa-a7z-gpu/arch-Xorg` 启动器，仅给 Arch X server 设置私有 GPU 环境。本体及 modesetting/glamor 模块来自 Arch。LightDM 会在启动程序后插入显示编号、seat、auth 等参数，因此不能直接把通用 `a7z-gpu-run /usr/lib/Xorg` 写成它的启动命令。

`arch-software` 直接启动 Arch Xorg，设置 `AccelMethod "none"` 与 `ShadowFB "true"`。两种模式都保留显示设备选择；XFCE 和 LightDM 的安装、用户会话以及服务启用由镜像配置负责。

## SDDM / Plasma X11

```sh
a7z-gpu-desktop print arch-glamor --display-manager sddm
sudo a7z-gpu-desktop enable arch-glamor --display-manager sddm
# SDDM 对应的软件显示回退。
sudo a7z-gpu-desktop enable arch-software --display-manager sddm
```

SDDM 使用 X11 greeter，相同的 Arch Xorg 启动器，以及仅作用于 greeter 的 Qt Quick 软件渲染设置。Wayland 会话目录指向专用空目录，X11 会话目录保留 `/usr/share/xsessions`。切换显示管理器时会移除另一显示管理器的受管片段，不会改变其系统服务状态。

KDE 镜像需要官方 `plasma-x11-session`，并独立设置初始 Plasma 软件渲染与关闭 KWin X11 合成。Xorg glamor、SDDM greeter 和 Plasma 客户端必须分别验收。上游 X11 生命周期、包集和配置范围见 [KDE 说明](../KDE.zh-CN.md)。

## 离线构建、切换与恢复

```sh
python3 gpu/a7z-gpu-desktop.py --root /path/to/rootfs \
  enable arch-glamor --display-manager sddm
```

目标 rootfs 必须已安装 Arch Xorg、所选显示管理器及所需 GPU 文件。工具写入配置后，下一次显示服务启动生效。需要立即切换时，先保存图形会话中的工作，再从文本终端或 SSH 执行对应命令：

```sh
sudo systemctl restart lightdm
# SDDM 系统使用这一条，不要同时启动两个显示管理器。
sudo systemctl restart sddm
```

重启显示管理器会结束当前图形会话。`a7z-gpu-desktop disable` 删除受管的 Xorg 和显示管理器片段，也会移除必需的 KMS 指定；排查显示问题应优先选择对应管理器的 `arch-software` 模式。

## 库隔离与边界

配置不创建全局 `LD_LIBRARY_PATH`，不替换 Mesa/libglvnd，不给整个会话套私有 GPU wrapper。应用可显式使用 `a7z-gpu-run PROGRAM`；T5 EGL 不支持 GLVND vendor 接口，不能通过伪造 EGL vendor JSON 接入。封装与探针说明见 [GPU README](README.zh-CN.md)。

X server 的 PowerVR glamor 不代表客户端 GLX 获得硬件加速。GLX/AIGLX 的兼容路径可能使用 DRISWRAST，深度 30 的部分读取格式也可能回退软件；应分别检查日志、实际桌面深度和客户端 renderer。EGL 像素探针与 Vulkan 设备枚举的通过范围有限，不能据此宣称任意 3D 程序、视频解码或 Wayland 已通过验收。

私有 `a7z-xorg` 只用于官方 Xorg 对照诊断，不是默认桌面服务器。二进制再分发范围见 [第三方许可说明](../THIRD-PARTY-LICENSES.zh-CN.md)。
