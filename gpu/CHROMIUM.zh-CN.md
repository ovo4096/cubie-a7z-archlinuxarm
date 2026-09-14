# Chromium 的 PowerVR 绘制入口

`a7z-chromium` 为 A7Z 的 X11 桌面选择 PowerVR Vulkan + ANGLE。它保留 Arch 的 Chromium、Mesa、GLVND 和系统库，通过原有 `/usr/bin/chromium` 启动浏览器。依赖 `chromium`、`python`、`glib2` 和本项目的 `radxa-a7z-gpu-userspace`；不需要额外 Python 模块。

在 Chromium 153、T5 GPU 用户态 24.2.6603887 下，独立实机实验已通过 GPU compositing、raster、Canvas 和 WebGL2 绘制。**这组参数不启用视频硬件解码**；标准 Chromium 的视频解码仍为软件路径。浏览器或驱动升级后应重新检查。

## 使用与回退

先正常退出全部 Chromium 窗口和后台实例，再从菜单打开 **Chromium（PowerVR）**，或执行：

```sh
a7z-chromium
```

它使用已有的标准用户资料目录，保留书签、扩展和登录状态。没有另建测试 profile。Chromium 会把同一 profile 的后续启动交给已运行的进程，因此仅点击另一个入口无法改变现有进程的渲染后端。启动器不终止进程或删除 profile 锁。[Chromium 用户资料目录说明](https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md)

需要回退时，正常退出全部实例，使用原来的 **Chromium** 菜单项恢复原有启动方式。要明确禁用 GPU，可使用 PowerVR 菜单项的“软件渲染”动作，或：

```sh
a7z-chromium --software
```

软件模式加入 `--disable-gpu`，只在 ICD 环境变量的整个值等于本项目 ICD 路径时清除该变量。用户自己的其他 ICD 路径或多驱动列表保持原样。两种模式都不写系统、浏览器或用户会话配置。

## 参数与用户配置

硬件模式仅给启动的浏览器进程设置：

```text
VK_DRIVER_FILES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json
VK_ICD_FILENAMES=/usr/share/radxa-a7z-gpu/vulkan/powervr_icd.json
--ozone-platform=x11
--use-gl=angle
--use-angle=vulkan
--enable-features=Vulkan,VulkanFromANGLE,DefaultANGLEVulkan
--no-default-browser-check
```

无需 `a7z-gpu-run`，也不注入 `LD_LIBRARY_PATH`、`LD_PRELOAD`、GBM/DRI 搜索路径、远程调试端口、沙箱关闭参数或 GPU blocklist 绕过参数；保留 Chromium 原有沙箱行为。已有的其他环境变量不被改写；请从普通桌面会话启动。

Arch 启动器依次读取 `/etc/chromium-flags.conf`、`$XDG_CONFIG_HOME/chromium-flags.conf`（未设 XDG 时为 `~/.config/chromium-flags.conf`），然后附加命令行参数。本工具使用同一个 GLib tokenizer 读取这些文件，不执行 shell 展开、不修改文件。对于 `--enable-features`，按通常后者覆盖前者的顺序取有效列表，再合并上述三个必需 feature；已有 feature 的参数或 trial 后缀保留。命令行中明确设置的 feature 列表优先于文件，其他参数原样交给 Arch 启动器。[Arch Chromium launcher 源码](https://github.com/foutrelis/chromium-launcher/blob/master/launcher.c)，[Chromium 参数解析](https://chromium.googlesource.com/chromium/src/+/main/base/command_line.cc)

若用户有效配置明确关闭必需 Vulkan feature、使用另一种 ANGLE/显示后端或关闭 GPU，本工具会报告冲突并退出，便于保留用户选择。使用原 Chromium 入口或 `--software` 可回退。配置文件中的 `--` 终止符会让后续启动参数失效，因此本工具会要求先移除该终止符；命令行的 `--` 则正常保留，其后的内容按文件/URL 传递。

## 安装集成与检查

由本项目 GPU 包安装两个独立文件：`a7z-chromium` → `/usr/bin/a7z-chromium`（0755）；`a7z-chromium.desktop` → `/usr/share/applications/a7z-chromium.desktop`（0644）。原 `/usr/bin/chromium`、`chromium.desktop` 和用户 flags 文件保持原样。该入口声明 HTTP/HTTPS、HTML/XHTML 支持，可在桌面设置中选为默认浏览器；文件本身不修改默认关联。[Chromium 官方 desktop 模板](https://chromium.googlesource.com/chromium/src/+/main/chrome/installer/linux/common/desktop.template)

Arch 启动器始终把浏览器内部 desktop 名称设为 `chromium.desktop`，即使系统已将 URL 关联到 `a7z-chromium.desktop`，浏览器也可能认为自己不是默认浏览器。硬件模式加入 `--no-default-browser-check`，只隐藏这一启动提示；它不更改默认关联。请在桌面的默认应用设置中选择 **Chromium（PowerVR）**，或以普通用户执行 `xdg-settings set default-web-browser a7z-chromium.desktop`。浏览器设置页的“设为默认”仍对应普通 `chromium.desktop`，会把关联切回标准启动方式。[Chromium 内部 desktop 名称](https://chromium.googlesource.com/chromium/src/+/153.0.8010.36/chrome/common/channel_info_posix.cc)，[默认应用检查与设置](https://chromium.googlesource.com/chromium/src/+/153.0.8010.36/chrome/browser/shell_integration_linux.cc)，[启动提示开关](https://chromium.googlesource.com/chromium/src/+/153.0.8010.36/chrome/browser/ui/startup/infobar_utils.cc)

打开 `chrome://gpu`，检查 Compositing、Rasterization、Canvas、WebGL/WebGL2 是否为硬件路径，渲染器是否包含 PowerVR / ANGLE Vulkan。不要把显示 Vulkan 可用或“Video Decode”标题本身当成硬件视频解码已通过；应结合具体状态及播放时媒体日志判断。`chrome://version` 可查看实际命令行与 profile 路径。

包装器的参数、配置文件语法、环境隔离和回退测试：

```sh
python3 -m unittest gpu/test_chromium_launcher.py -v
```

这些测试不启动浏览器。完整验收还应在安装后正常启动标准用户 profile，复查 `chrome://gpu` 并验证软件回退。
