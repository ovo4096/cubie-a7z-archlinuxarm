# T5 PowerVR 用户态封装

本工具将 Radxa Cubie A7Z 的官方 T5 PowerVR 用户态重新封装为 Arch Linux ARM 包，目标为 `6.6.98-4-aw2511` BSP、PowerVR `24.2.6603887`、BVNC `36.56.104.183`。内核模块和固件由独立 BSP 包提供，用户态包不替换系统内核。

## 包与安装布局

| 包 | 内容 |
|---|---|
| `radxa-a7z-gpu-userspace` | 私有 EGL/GLES/GBM、Vulkan ICD、诊断工具及桌面配置选择器 |
| `radxa-a7z-gpu-compat` | 可选官方 Xorg 所需的私有 OpenSSL 1.1 兼容库 |
| `radxa-a7z-gpu-xorg` | 可选官方 Xorg 和随 GPU 提供的模块，用于对照诊断 |

GPU 库安装在 `/usr/lib/radxa-a7z-gpu/`，Arch 的 Mesa、libglvnd、Vulkan loader 和 Xorg 本体保持由 Arch 包管理。官方 ELF 的 `/usr/local/lib` RPATH 改为对象相对的私有 RUNPATH，来源清单同时记录原始文件与安装文件的 SHA256。不复制完整 Debian `/usr/lib`、glibc 或 libstdc++。

包安装本身不启用显示管理器、不设置全局库搜索路径。默认桌面采用 Arch Xorg；可选官方 Xorg 与 OpenSSL 兼容包不属于该路径的必要组件。

## 构建和静态审计

Linux 构建机需要 Python 3.11+、binutils、patchelf、GNU tar、zstd；libarchive-tools 可用于生成 `.MTREE`。输入必须是保留 dpkg 数据库的官方 T5 rootfs，脚本校验 GPU 包 `1.0.1` 与 `libssl1.1 1.1.1n-0+deb11u4`。

```sh
# 构建并审计全部三个组件。
python3 tools/package_gpu.py \
  --vendor-root /path/to/official-t5 \
  --target-root /path/to/arch-rootfs \
  --output /path/to/packages/gpu-all --strict

# CLI 或不使用官方 Xorg 的构建，可只生成实际需要的用户态包。
python3 tools/package_gpu.py \
  --vendor-root /path/to/official-t5 \
  --target-root /path/to/arch-rootfs \
  --output /path/to/packages/gpu-userspace \
  --components userspace --strict
```

`--inspect-only` 只写报告，不生成包；`--strict` 要求目标 rootfs 存在且所选组件没有缺失的动态库或符号版本。`gpu-dependency-report.json` 中的 `audited_components` 标明范围，用户态通过不代表可选官方 Xorg 也通过。

静态检查覆盖递归 `DT_NEEDED` 与版本化符号，不能代替普通导入符号、运行期 `dlopen`、内核/用户态 ABI 或硬件测试。构建时应使用独立输出目录，避免将同一组件的不同版本混入安装通配符。

## 隔离动态加载检查

三个包齐全且目标 Arch rootfs 已安装其依赖时，可在带 `qemu-aarch64-static` 的宿主运行：

```sh
bash gpu/validate-userspace.sh \
  /path/to/arch-rootfs /path/to/packages/gpu-all /path/to/reports
```

该脚本要求目录内每个组件恰好一个包，将载荷解到报告目录内的独立临时目录，用目标 Arch 库执行 `RTLD_NOW` 与可选官方 `Xorg -version`，不修改目标 rootfs，也不访问 GPU。它不能直接用于只有 userspace 包的目录。

## 显式选择 GPU 库

在安装了匹配 BSP 与用户态包的开发板上执行：

```sh
a7z-gpu-run a7z-gpu-link-check
a7z-gpu-run a7z-gpu-probe --api egl
a7z-gpu-run a7z-gpu-probe --api all
a7z-gpu-run vulkaninfo --summary
```

探针需要 Python，`vulkaninfo` 来自 `vulkan-tools`。`a7z-gpu-run` 只为其后启动的进程设置私有库、DRI、GBM 路径和 Vulkan ICD；不要通过 `source` 导入 shell，也不要把整个登录会话放进该 wrapper。私有目录后明确使用 `/usr/lib`，Vulkan loader 保持使用 Arch 版本。

T5 EGL 没有导出 GLVND vendor 接口所需的 `__egl_Main`，因此不创建 EGL vendor JSON。EGL/GLES/GBM 通过 wrapper 的进程级 `LD_LIBRARY_PATH` 选择；主动加载绝对路径库的程序可能需要单独适配。Vulkan 使用专用 ICD JSON 选择 `libVK_IMG.so.1`，其中 API 版本为此固定 ICD 报告的 `1.3.277`。

EGL 探针先尝试 surfaceless，再尝试 GBM，创建 GLES2 上下文并读取 1×1 红色像素；它要求 PowerVR/Imagination 等硬件标识，拒绝将软件 renderer 判为成功。需要指定 GBM 节点时可使用：

```sh
a7z-gpu-run a7z-gpu-probe --api egl --device /dev/dri/renderD128
```

节点名称以目标系统为准。缺少 DRM 节点、不支持所需 EGL 配置或返回软件 renderer 均属于失败。Vulkan 探针只枚举真实 GPU，不提交 draw/compute；动态库加载、像素绘制和设备枚举均不能代替长期稳定性测试。

## 桌面与可选官方 Xorg

KDE 默认让原版 Qt 的 SDDM/Plasma 使用 PowerVR Vulkan ICD，已验证动画窗口和实际桌面呈现。此路径依赖 ICD 自带的私有 RUNPATH，无需向 Qt 注入 `LD_LIBRARY_PATH` 或 `LD_PRELOAD`。KWin 的 EGL 窗口 surface 创建仍复现崩溃，合成暂时关闭；软件回退和环境继承边界见 [KDE 说明](../KDE.zh-CN.md)。命令行 Vulkan 探针本身仍仅检查枚举，界面验收是另行完成的实机检查。

Arch Xorg 的 LightDM/SDDM 配置见 [桌面说明](DESKTOP.zh-CN.md)。X server glamor 与客户端 GLX 是不同路径；本项目不承诺 GLX 客户端硬件加速，也不以 Vulkan 枚举代替 Vulkan 渲染验收。

安装三个组件及可选 Xorg 依赖后，`a7z-xorg -version` 可检查官方 Xorg 的加载。该服务器使用私有模块路径，不自动启动会话。其 `libcrypto.so.1.1` 依赖由 compat 包提供；该兼容库只用于这一诊断路径。官方包仅附带部分 Xorg 模块，完整输入、GLX 和会话兼容性仍需独立检查。

## 上游与许可

- [官方 T5 manifest](https://github.com/radxa-build/radxa-a733/releases/download/rsdk-t5/radxa-a733_trixie_cli_t5.manifest)
- [固定 Allwinner prebuilt 发布](https://github.com/radxa-pkg/allwinner-prebuilt/releases/tag/1.4.10-2)
- [官方图形 profile](https://github.com/radxa-pkg/allwinner-profiles/blob/0.2.9/debian/control)

封装工具保留上游 copyright；未提供明确 GPU copyright 时生成 `UPSTREAM-NOTICE.txt`，不推定或虚构许可。开源构建脚本的公开不等于闭源 GPU、固件或其修改版本已获公开再分发授权。具体发布范围与尚待核定项目见 [第三方许可说明](../THIRD-PARTY-LICENSES.zh-CN.md) 和 [发布说明](../RELEASE.zh-CN.md)。
