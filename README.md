# cubie-a7z-archlinuxarm

Radxa Cubie A7Z 的 Arch Linux ARM 移植：使用锁定的官方 **T5 / Trixie BSP**，保留 U-Boot、设备树、内核、无线模块和配套 GPU 用户态，提供 CLI、XFCE、KDE 三种独立构建变体以及 SD / UFS 两种整盘镜像。

[安装到 SD / UFS](INSTALL.zh-CN.md) · [发行说明与验证范围](RELEASE.zh-CN.md) · [首次启动 Wi-Fi](WIFI-FIRSTBOOT.zh-CN.md) · [KDE 说明](KDE.zh-CN.md) · [公开镜像清理](RELEASE-HYGIENE.zh-CN.md) · [滚动升级](ROLLING-UPGRADE.zh-CN.md) · [第三方许可](THIRD-PARTY-LICENSES.zh-CN.md)

源码位于本仓库；镜像、校验清单和对应构建记录通过 [GitHub Releases](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases) 发布。请以具体 release 的资产和验证表为准，源码中的变体支持不等于每个变体都完成了相同的硬件验收。

## 选择镜像

| 变体 | 默认环境 | 主要配置 |
|---|---|---|
| `cli` | SSH、NetworkManager、维护工具，无桌面 | 适合无显示器运行或作为 UFS 安装用 SD；不安装浏览器和输入法 |
| `xfce` | XFCE + LightDM + Arch Xorg | XRender/XPresent 合成、预装 Chromium（PowerVR）和 Fcitx5 + Rime |
| `kde` | Plasma X11 + SDDM | Qt Quick 界面使用 PowerVR Vulkan，预装同一 Chromium 优化与 Fcitx5 + Rime；KWin 合成关闭 |

文件名采用 `cubie-a7z-archlinuxarm-{cli|xfce|kde}-t5-{sd-512|ufs-4096}.img.zst`。SD 镜像用于 512 字节逻辑扇区，UFS 镜像用于 4096 字节逻辑扇区；两者不可互换。首次启动自动扩展最后一个 ext4 根分区。

此前实机适配验证了 EGL/GLES 硬件绘制、Arch Xorg glamor，以及 Qt 动画窗口、SDDM 登录界面和 Plasma 桌面的 PowerVR Vulkan 渲染。KDE 保留 Arch Qt/Mesa/GLVND，用私有 Vulkan ICD 选择 GPU；未向桌面注入私有 EGL 库路径或预加载适配库。KWin 的 EGL 窗口创建仍会崩溃，合成暂时关闭；GLX/AIGLX 客户端仍使用软件路径。Wayland、通用 Vulkan 计算/游戏和长时间负载未因此得到验证。每版镜像的验收范围见发行说明。

`v0.2.0-t5` 的桌面配方把 [Chromium（PowerVR）入口](gpu/CHROMIUM.zh-CN.md) 和浏览器一同预装，默认网页关联使用该入口；两种桌面均预设简体中文会话、中文字体和 Rime「朙月拼音·简化字」。按 `Ctrl+Space` 切换中英文，初始为英文；第一次启用 Rime 会自动部署词典。用户词库和浏览器资料在用户自己的系统中创建，公开镜像不携带个人数据。

Chromium 的网页合成、Canvas、WebGL 和栅格化此前已在 XFCE 实机通过 PowerVR Vulkan 验证，[验收记录](gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md)包含受控性能比较。**Chromium 内的视频硬解仍未接通**：GPU 网页绘制不等于视频硬件解码。本版 XFCE/KDE 镜像同时预装 [Cedar/OMX 视频包](vpu/README.zh-CN.md)与 GStreamer，可通过 `a7z-vpu-run` 选择独立的 H.264 硬解路径；CLI 未安装这个 VPU 包。独立硬解不能靠安装包或额外浏览器参数自动接入 Chromium。最终镜像的硬件验收以 [发行说明](RELEASE.zh-CN.md)为准。

## 烧录与无显示器启动

完整命令见 [SD / UFS 安装指南](INSTALL.zh-CN.md)。先下载镜像、对应 `.img.sha256` 和 release 的 `SHA256SUMS`，校验压缩包、解压，再校验原始镜像。需要无显示器自动联网时，用 [Wi-Fi 向导](WIFI-FIRSTBOOT.zh-CN.md)生成 `-private.img` 后烧录私人副本；SD 网络配置不会自动进入另一个 UFS 镜像。

**SD：** 使用电脑读卡器烧录已解压的 `sd-512.img`，完成工具的写后校验，断电插入开发板再上电。[板载 SD 维护脚本](tools/flash_sd.py)保留 CID、挂载、容量检查和完整回读；电脑 USB 读卡器通常不是 `mmcblk`，使用电脑烧录工具即可。

**UFS 主要方式：** 从 SD 正常启动后，在板上下载所需 `ufs-4096.img.zst`，校验并解压到 SD，核对 UFS 整盘、4096 字节扇区及未挂载状态，再通过 `dd bs=4M conv=fsync` 写入、完整回读、迁移备份 GPT。完成后关机、拔 SD、再上电。这个流程遵循 [官方 UFS 安装方法](https://docs.radxa.com/cubie/a7z/getting-started/install-system/ufs)，具体命令与设备识别要求见安装指南。

**UFS 第二选项：** 使用 `a7z-install-ufs --dry-run` 先预览，再由安装器完成写入、完整回读和 GPT 调整。安装器拒绝当前根盘、已挂载设备、4 MiB boot LUN、错误扇区或不足容量。两种方式都写整盘 `.img`，不写压缩包或单个分区。

首次登录用户为 `alarm`，初始登录密码为 `alarm`；root 账号锁定。请首次登录后立即运行 `passwd`。公开镜像没有固定的 SSH 主机密钥；它们在首次启动生成。使用路由器 DHCP 客户端列表寻找设备，连接前核实新的 SSH 主机身份。

## 从源码构建

需要 Linux root 环境；Windows 使用 WSL2 Ubuntu。构建 rootfs 和工作目录必须放在 WSL 原生 Linux 文件系统，下载缓存和最终产物可以位于 Windows 挂载盘。Ubuntu 构建依赖：

```sh
sudo apt-get install -y python3 python3-venv qemu-user-static binfmt-support \
  util-linux fdisk dosfstools e2fsprogs rsync libarchive-tools binutils \
  patchelf zstd xz-utils gzip tar kmod gdisk mtools build-essential patch \
  gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu
sudo /usr/lib/systemd/systemd-binfmt
cat /proc/sys/fs/binfmt_misc/qemu-aarch64
```

非 ARM 构建机必须看到处理器已 `enabled`，flags 包含 `F`。上述 systemd-binfmt 命令适用于提供 `/usr/lib/binfmt.d/qemu-aarch64.conf` 的 Ubuntu；旧发行版若通过 binfmt-support 注册，使用其 `update-binfmts --enable qemu-aarch64`，然后同样核查实际状态。

PowerVR 内核模块包含本项目的 [fdinfo 修复](gpu/kernel/README.md)，从锁定 T5 rootfs 中的 DKMS 源码及匹配头文件编译，不能直接沿用旧的预编译模块。编译在构建机的独立临时目录中进行，不修改官方输入，也不要求开发板在首次启动时运行 DKMS。模块按官方格式使用 XZ CRC32 校验与 1 MiB 字典，以匹配 T5 内核的模块解压器。

```sh
sudo python3 tools/build.py --variant xfce --work-dir /root/a7z-build/xfce
sudo python3 tools/build.py --variant cli --work-dir /root/a7z-build/cli
sudo python3 tools/build.py --variant kde --work-dir /root/a7z-build/kde
```

每个变体必须使用独立、全新的工作目录。Windows 可从 PowerShell 运行同样的 Python 命令，工具会转交给 WSL。默认 XFCE；`--plan` 只预览，`--resume` 只复用源锁、配方、变体和配置均相同的构建目录。失败后的目录保留，不递归删除用户目录；需要重新解包时选择新的工作目录。

上面的三个构建命令应顺序执行。同一挂载命名空间中的并行构建可能让 chroot 继承另一份镜像的临时挂载，导致卸载后文件系统检查仍报告正在使用；需要并行时使用彼此隔离的 Linux 构建环境。WSL 重新启动后，自行挂载的 ext4 构建卷需要重新挂载；恢复前用 `findmnt -T` 核对实际工作目录所在卷，不能仅凭目录仍存在或 `--resume` 判断挂载正常。

流程依次为锁定源下载校验、独立 rootfs 解包、Arch 包安装、BSP/GPU/base 包生成、启动配置、公开镜像清理、两种镜像组装、压缩和审计。构建记录包含每个已完成阶段及镜像、压缩包的完整哈希。`--stop-after` 可停在明确阶段。可用 `--root-size-mib` 指定初始根分区大小；默认按内容估算。KDE 体积较大，应预留足够空间。

本次发行镜像采用增量构建：复用构建机上经过清理检查的同变体预制 rootfs，重新执行完整 `pacman -Syu`、全部板级包的打包与安装、启动配置和镜像清理，再生成新的 SD/UFS 镜像。此次没有重新解包 Arch 初始归档，也没有从开发板导入系统、网络配置或用户数据。完成审计后，`build-manifest-*.json` 的 `input_reuse` 字段记录复用来源的源码、旧构建状态、包清单、清理报告和 GPU 来源信息的 SHA256，并用 `fresh_arch_seed_extracted=false` 明确标记解包范围；最终文件的实机结果仍单独列在 [发行说明](RELEASE.zh-CN.md)。

固定输入见 [config/sources.lock.json](config/sources.lock.json)：T5 内核 `6.6.98-4-aw2511`、配套 U-Boot 和官方 rootfs。`pacman -Syu` 使用滚动仓库，因此固定初始归档不代表以后逐字节重建；工具记录最终包版本、缓存 SHA256、构建配方和镜像哈希，供审计本次结果。

本项目不会把 Debian 的 `/usr/lib` 整体覆盖到 Arch。闭源/预编译 GPU 用户态放在私有目录，Arch Xorg 本体和 Mesa/libglvnd 保留；调用指定 GPU 路径时才使用 wrapper。进一步说明见 [GPU 使用文档](gpu/README.zh-CN.md)。第三方组件的许可证、来源和当前证据边界见 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)，不能将项目 MIT 许可证理解为第三方载荷已全部取得同样授权。

## 测试与源码导出

以下测试在 Linux / WSL 中运行，依赖 Linux 路径、权限和设备语义；不要在 Windows 原生 Python 中运行完整测试集。本次修订对应的 140 项测试已通过：91 项主测试、16 项 BSP 包测试、28 项 GPU 测试和 5 项 VPU 包测试。另有此前通过的 4 组根分区扩容真实 loop 测试，覆盖 512/4096 字节扇区及是否预先执行 `sgdisk -e`；该扩容实现未改动。这些检查不替代最终镜像的实机验收。

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s packages/tests -p 'test_*.py' -v
python3 -m unittest discover -s gpu -p 'test_*.py' -v
python3 -m unittest discover -s vpu -p 'test_*.py' -v
python3 tools/export_source.py --plan
python3 tools/export_source.py --output out/source-release
```

镜像/安装器 loop 集成测试需要 Linux root 和明确的新测试目录；[Wi-Fi 镜像集成测试](tests/integration_personalize.py) 不需要 root 或设备访问。测试脚本生成的是测试夹具，不能用于启动开发板。

源码导出只复制明确白名单，缺文件、私密模式匹配或指向未导出记录的本地文档链接都会拒绝。目标必须是新目录；不导出开发仓库历史、SSH/串口私人 helper、实机记录、备份、下载缓存或二进制产物。导出目录自带源码 manifest 与 SHA256 清单。项目自身代码和文档采用 [MIT](LICENSE)；第三方组件单独遵循其许可证。
