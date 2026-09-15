# A7Z T5 HDMI 内核补丁

CLI、KDE、XFCE 共用 `linux-radxa-a7z 6.6.98_4-2`。内核 release 仍是
`6.6.98-4-aw2511`，保留原厂设备树、模块和功能配置；PowerVR 模块继续包含
[fdinfo 修复](../../gpu/kernel/README.md)。本目录的补丁针对共同的 HDMI/DRM 驱动，不依赖桌面。

## 修复内容与边界

原 BSP 的 HPD 拔出处理会关闭发送端、清除私有模式状态，却保留 DRM CRTC 的
active 状态；重新连接仅通知热插拔，没有提交新模式的 CLI 会一直无信号。
补丁删除 HPD 线程中的这组动作，由原有 atomic 和 PM 回调继续管理模式及输出。
真实 HPD 检测、50 ms 二次读取、EDID/CEC 缓存失效和热插拔通知保持原样。
没有强制 HPD、固定分辨率或恢复轮询脚本。

所复用的内核此前已在 CLI 完成启动、同一显示器拔插和再次启动观察。
v0.2.2 的发布构建不再执行实机或桌面测试，不能视为 KDE/XFCE 已验证通过。
此补丁没有新增换显示器自动选模式、无屏启动后接屏或休眠恢复功能。
拔线时也不再通过旧 disable 调用隐式停止 HDCP；受保护视频的重新认证未验证。
Chromium、GPU 加速和输入法配置与本内核补丁无关，继续使用现有实现。

## 本次发布使用锁定构建输入

[输入锁](build-input.lock.json) 固定四个上游源码 commit、源码归档 SHA256、补丁、
原厂配置，以及已经构建的 `Image`、`config`、`System.map` 的大小和 SHA256。
发布页的 `hdmi-kernel-input` 归档仅包含这三个文件及 `provenance.json`。
它没有原始工作目录、串口记录、网络配置或其他诊断文件。

解压后可直接交给 BSP 打包器：

```sh
python3 tools/package_bsp.py \
  --vendor-root /srv/a7z/vendor-t5 \
  --hdmi-kernel-input /srv/a7z/hdmi-kernel-input \
  --output /srv/a7z/packages/bsp
```

维护者从原始候选输出整理这四个公开文件时使用：

```sh
python3 tools/build_hdmi_kernel.py prepare-input \
  --candidate /srv/a7z/candidate-output \
  --output /srv/a7z/hdmi-kernel-input
```

`prepare-input` 只接受输入锁中的三个完全匹配的文件，并重新生成公开 provenance；
不会复制候选目录中的原始日志。打包时必须提供该输入，缺失或校验失败会停止，
不会回退到未修复的厂商 Image。安装到 `/boot/vmlinuz-6.6.98-4-aw2511` 的内容是
raw ARM64 Image，不是 gzip；同时替换匹配的 config 和 System.map。

## 从源码重新构建

源码构建和本次复用二进制是两个明确的输入模式。源码模式验证锁定归档、补丁、
原厂配置、编译工具版本和 UTS release；记录实际输出 SHA256，**不要求新输出
与旧候选逐字节相同**。固定 `--source-date-epoch`、构建身份和源码路径映射，
便于在同一工具链上重建。它不宣称不同发行版编译器会产生相同二进制。

需要 Linux、Python 3.12+、GNU make、patch、bison、flex、host gcc/g++、
libelf/OpenSSL 开发头文件、AArch64 GCC 14.2.0 和 GNU binutils 2.44。
工具不安装或升级宿主软件，也不访问开发板。使用 binutils 2.44 是为了保留
官方 `CONFIG_RELR=y`，不能通过关闭该选项适配旧链接器。

1. 准备解包且不修改的官方 T5 rootfs，含 `usr/src/linux-headers-6.6.98-4-aw2511`。
2. 按输入锁的 URL 获取四个源码归档，以 `name-commit.tar.gz` 命名，放入一个目录。
   脚本会检查大小与 SHA256。此处包含完整 GPL 内核和 BSP 的上游来源。
3. 准备一个私有 GNU binutils 2.44 AArch64 prefix，或使用已存在且版本匹配的工具。
4. 运行：

```sh
python3 tools/build_hdmi_kernel.py build \
  --vendor-root /srv/a7z/vendor-t5 \
  --archives /srv/a7z/source-archives \
  --work-dir /srv/a7z/new-kernel-work \
  --output /srv/a7z/new-kernel-input \
  --cc aarch64-linux-gnu-gcc-14 \
  --binutils-prefix /opt/a7z-binutils-2.44 \
  --source-date-epoch 1789484513 --jobs 4
```

工作目录和输出目录必须不存在。脚本按 Radxa wrapper 布局连接 BSP 和设备树，
应用本目录补丁，沿用原厂配置，仅允许 `CONFIG_CC_VERSION_TEXT` 的文本差异。
构建原始 Image 后生成相同的四文件输入接口，可交给 `package_bsp.py`。
完整编译日志留在工作目录，不会加入公开 provenance 或系统镜像。

私有 binutils 的源码 URL、大小、SHA256 也在输入锁中。源码解压并校验后，在新目录
配置和安装到自选的私有 prefix；下面命令不会写入发行版 `/usr`：

```sh
../binutils-2.44/configure --prefix=/opt/a7z-binutils-2.44 \
  --target=aarch64-linux-gnu --disable-gdb --disable-gprofng --disable-gprof \
  --disable-nls --disable-werror --disable-gold --disable-sim \
  --disable-libdecnumber --disable-readline --disable-multilib \
  --enable-plugins --enable-new-dtags --enable-default-hash-style=gnu --with-sysroot
make -j4 MAKEINFO=true all-binutils all-gas all-ld
make MAKEINFO=true install-binutils install-gas install-ld
```

## 同步包依赖

内核包版本更新时，无线模块、GPU 模块和 VPU 包的严格内核依赖一并更新。
GPU 用户态及其 Xorg 包也同步 GPU 模块依赖；厂商用户态二进制保持原样。
滚动升级应使用同一次发布的整组包，避免混装旧严格依赖包和新内核包。
旧桌面 HDMI 钩子由新的 base 包迁移工具移除，启动由共用内核负责。
