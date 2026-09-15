# cubie-a7z-archlinuxarm

Radxa Cubie A7Z 的 Arch Linux ARM 移植，基于锁定的官方 **T5 / Trixie BSP**，提供 CLI、XFCE、KDE 各自的 SD / UFS 整盘镜像。

**[v0.2.1-t5](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/tag/v0.2.1-t5)** 为 XFCE / KDE 加入 HDMI 启动恢复：按已连接显示器的有效 EDID、当前 / 优选模式及驱动状态判断，不限定型号或固定分辨率。正常输出保持原样；发现持续的输出关闭异常时先普通重启输出，仍异常才保持 HPD 连接兜底。CLI 不启用，没有 USB 修复。**新增通用逻辑及本次新镜像均未运行自动化、滚动升级或实机启动测试。** 适用范围与热插拔限制见 [HDMI 说明](desktop/HDMI.zh-CN.md)。此前单款显示器的恢复记录不能代表多型号适配已通过验证。

[SD / UFS 安装](INSTALL.zh-CN.md) · [发行说明](RELEASE.zh-CN.md) · [烧录前 Wi-Fi](WIFI-FIRSTBOOT.zh-CN.md) · [KDE](KDE.zh-CN.md) · [镜像清理](RELEASE-HYGIENE.zh-CN.md) · [滚动升级](ROLLING-UPGRADE.zh-CN.md) · [第三方许可](THIRD-PARTY-LICENSES.zh-CN.md)

## 选择镜像

| 变体 | 默认环境 | 主要配置 |
|---|---|---|
| `cli` | SSH、NetworkManager、维护工具，无桌面 | 适合无显示器运行或作为 UFS 安装用 SD；不安装浏览器和输入法 |
| `xfce` | XFCE + LightDM + Arch Xorg | XRender / XPresent 合成、Chromium（PowerVR）、Fcitx5 + Rime 和 HDMI 启动兼容处理 |
| `kde` | Plasma X11 + SDDM | Qt Quick 使用 PowerVR Vulkan，同一 Chromium / Rime 和 HDMI 启动兼容处理；KWin 合成关闭 |

文件名为 `cubie-a7z-archlinuxarm-{cli|xfce|kde}-t5-{sd-512|ufs-4096}.img.zst`。SD 使用 **512 字节**逻辑扇区，UFS 使用 **4096 字节**；两种镜像不可互换。首次启动自动扩展根分区。

桌面预设简体中文和中文字体，Rime 使用「朙月拼音·简化字」，按 **Ctrl+Space** 切换中英文，初始为英文。首次启用时自动部署词典；公开镜像不带个人词库或浏览器资料。

默认浏览器入口为 [Chromium（PowerVR）](gpu/CHROMIUM.zh-CN.md)，沿用已有的 PowerVR Vulkan 网页绘制配置。**Chromium 内的视频硬解仍未接通**；XFCE / KDE 预装的 [Cedar / OMX 与 GStreamer](vpu/README.zh-CN.md)提供独立 H.264 硬解路径，两者不能混同。KDE 保留 Arch Qt / Mesa / GLVND，采用私有 Vulkan ICD；KWin 合成关闭，GLX / AIGLX 仍是软件路径，Wayland 未适配。本版没有新增 GPU / 视频优化。

## 烧录与无显示器启动

完整命令见 [安装指南](INSTALL.zh-CN.md)。下载镜像、对应 `.img.sha256` 和 release 的 `SHA256SUMS`，校验压缩包，解压后再校验原始镜像。

**SD：** 用电脑读卡器将解压后的 `sd-512.img` 写入整张卡，完成写后校验，关机插卡再上电。

**UFS 主要方式：** 先从 SD 启动，在板上下载 `ufs-4096.img.zst`，校验并解压到 SD。核对 UFS 整盘、4096 字节扇区及未挂载状态，通过 `dd` 写入、完整回读、迁移备份 GPT；成功后关机、拔卡、上电。这个流程与 [官方 UFS 安装方式](https://docs.radxa.com/cubie/a7z/getting-started/install-system/ufs)一致。

**UFS 第二选项：** 先用 `a7z-install-ufs --dry-run` 预览，再由项目安装器执行写入、完整回读与 GPT 调整。两种方法都写原始整盘 `.img`，不写压缩包或单个分区。

需要首次启动自动联网时，用 [Wi-Fi 向导](WIFI-FIRSTBOOT.zh-CN.md)预先生成 `-private.img`，再烧录私人副本。SD 的网络配置不会自动进入另一个 UFS 镜像；私人副本不能再公开分发。

初始用户 / 密码为 `alarm` / `alarm`，root 锁定，无自动登录；首次登录后执行 `passwd`。SSH 主机密钥在首次启动生成，可从路由器 DHCP 列表找到设备并核对新主机身份。

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

v0.2.1 是显示兼容补丁发行版：只读复用 v0.2.0 最终 R5 构建的干净离线 rootfs，复制到新构建卷后升级 `radxa-a7z-base 0.1.0-5`；GUI 另安装 `xorg-xrandr 1.5.4-1` 和显示管理器启动 / 停止钩子。执行构建清理后，重新生成带独立 UUID 的六张镜像。本轮没有执行 `pacman -Syu`，内核、GPU、Chromium 和 Rime 等包保持原版本。这个补丁发行流程与上面的通用全流程构建命令不同，具体输入和产物哈希见发布页构建记录；没有从测试板导入系统、网络配置或用户数据。

固定输入见 [config/sources.lock.json](config/sources.lock.json)：T5 内核 `6.6.98-4-aw2511`、配套 U-Boot 和官方 rootfs。`pacman -Syu` 使用滚动仓库，因此固定初始归档不代表以后逐字节重建；工具记录最终包版本、缓存 SHA256、构建配方和镜像哈希，供审计本次结果。

本项目不会把 Debian 的 `/usr/lib` 整体覆盖到 Arch。闭源/预编译 GPU 用户态放在私有目录，Arch Xorg 本体和 Mesa/libglvnd 保留；调用指定 GPU 路径时才使用 wrapper。进一步说明见 [GPU 使用文档](gpu/README.zh-CN.md)。第三方组件的许可证、来源和当前证据边界见 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)，不能将项目 MIT 许可证理解为第三方载荷已全部取得同样授权。

## 开发测试与源码导出

仓库保留开发测试命令，供后续开发运行；**v0.2.1 发布没有执行这些测试，也没有开展新镜像硬件启动或滚动升级回归**。v0.2.0 的测试记录属于历史结果，不作为本版验收结论。

以下命令需要 Linux / WSL 的路径、权限和设备语义，不应在 Windows 原生 Python 中运行完整测试集：

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s packages/tests -p 'test_*.py' -v
python3 -m unittest discover -s gpu -p 'test_*.py' -v
python3 -m unittest discover -s vpu -p 'test_*.py' -v
python3 tools/export_source.py --plan
python3 tools/export_source.py --output out/source-release
```

源码导出使用明确白名单，不导出开发仓库历史、SSH / 串口私人 helper、实机记录、备份、下载缓存或二进制产物；导出目录附源码 manifest 与 SHA256 清单。目标须为新目录。镜像安装器的 loop 集成测试另需 Linux root 和专用新目录，生成的测试夹具不能用于开发板启动。

项目自身代码和文档采用 [MIT](LICENSE)，第三方组件分别遵循上游许可证。
