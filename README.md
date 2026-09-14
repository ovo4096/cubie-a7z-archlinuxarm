# cubie-a7z-archlinuxarm

Radxa Cubie A7Z 的 Arch Linux ARM 移植：使用锁定的官方 **T5 / Trixie BSP**，保留 U-Boot、设备树、内核、无线模块和配套 GPU 用户态，提供 CLI、XFCE、KDE 三种独立构建变体以及 SD / UFS 两种整盘镜像。

[发行说明与验证范围](RELEASE.zh-CN.md) · [首次启动 Wi-Fi](WIFI-FIRSTBOOT.zh-CN.md) · [KDE 说明](KDE.zh-CN.md) · [公开镜像清理](RELEASE-HYGIENE.zh-CN.md) · [滚动升级](ROLLING-UPGRADE.zh-CN.md) · [第三方许可](THIRD-PARTY-LICENSES.zh-CN.md)

源码位于本仓库；镜像、校验清单和对应构建记录通过 [GitHub Releases](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases) 发布。请以具体 release 的资产和验证表为准，源码中的变体支持不等于每个变体都完成了相同的硬件验收。

## 选择镜像

| 变体 | 默认环境 | SD / UFS 硬件状态 |
|---|---|---|
| `cli` | SSH、NetworkManager、维护工具，无桌面 | 构建与验证中 |
| `xfce` | XFCE + LightDM + Arch Xorg | 两种介质已实测启动、网络、扩容和桌面 |
| `kde` | Plasma X11 + SDDM，客户端采用软件渲染默认值 | 构建与验证中 |

文件名采用 `cubie-a7z-archlinuxarm-{cli|xfce|kde}-t5-{sd-512|ufs-4096}.img.zst`。SD 镜像用于 512 字节逻辑扇区，UFS 镜像用于 4096 字节逻辑扇区；两者不可互换。首次启动自动扩展最后一个 ext4 根分区。

GPU 已验证 EGL/GLES 硬件绘制、Arch Xorg glamor 和 Vulkan GPU 枚举。GLX/AIGLX 客户端仍使用软件路径；Vulkan 渲染/计算、Wayland、视频编解码和长时间负载未因此得到验证。CLI/KDE 的细分状态以发行说明为准。

## 烧录与无显示器启动

先校验 release 的 `SHA256SUMS`，再用 `zstd -d 文件.img.zst` 解压。需要无显示器自动联网时，按 [Wi-Fi 向导](WIFI-FIRSTBOOT.zh-CN.md) 创建带 seed 的 `-private.img`，然后烧录该私人副本；公开镜像不包含个人 Wi-Fi 配置或 SSH 公钥。

**SD：** 使用支持原始 `.img` 的电脑读卡器烧录工具，选择 SD 卡并完成写入校验，与 [官方 SD 安装流程](https://docs.radxa.com/en/cubie/a7z/getting-started/install-system/microsd) 相同。Linux 也可在确认整个目标设备、卸载其所有分区后写入：

```sh
lsblk -o NAME,SIZE,MODEL,TYPE,MOUNTPOINTS
# 把 /dev/sdX 替换为已核实的整张 SD 卡，不能是系统盘或分区。
sudo dd if=cubie-a7z-archlinuxarm-xfce-t5-sd-512.img of=/dev/sdX bs=4M conv=fsync status=progress
```

板载 SD 的维护脚本 [tools/flash_sd.py](tools/flash_sd.py) 提供 CID/挂载/容量检查、默认只读预览和完整回读。电脑 USB 读卡器设备通常不是 `mmcblk`，应使用电脑烧录工具。SD 应在上电前插入；本板实测无卡启动 UFS 后热插 SD 可能不识别，详见发行说明。

**UFS：** 从已可启动的 SD 系统进入，将 UFS 原始镜像及其 `.img.sha256` 放到 SD 系统可读位置，先预览：

```sh
sudo a7z-install-ufs --image cubie-a7z-archlinuxarm-xfce-t5-ufs-4096.img --target /dev/sda --dry-run
sudo a7z-install-ufs --image cubie-a7z-archlinuxarm-xfce-t5-ufs-4096.img --target /dev/sda
```

实际写入须输入完整的目标确认文本。安装器拒绝当前根盘、已挂载设备、非 UFS 控制器、4 MiB boot LUN、错误扇区或不足容量，写入后完整回读并修复备份 GPT。可加 `--grow-root` 在安装时离线扩容，也可以交给首次启动扩容。完成后关机、拔 SD、再上电，从 UFS 启动。流程与 [官方 UFS 安装模式](https://docs.radxa.com/en/cubie/a7z/getting-started/install-system/ufs) 相同。

在官方 Debian SD 系统运行仓库安装器时，先安装 `python3 util-linux fdisk gdisk e2fsprogs`，然后用 `sudo python3 runtime/a7z-install-ufs ...`。安装器只接受原始 `.img`，不接受压缩包或 PhoenixSuit 专用固件。

首次登录用户为 `alarm`，初始登录密码为 `alarm`；root 账号锁定。请首次登录后立即运行 `passwd`。公开镜像没有固定的 SSH 主机密钥；它们在首次启动生成。使用路由器 DHCP 客户端列表寻找设备，连接前核实新的 SSH 主机身份。

## 从源码构建

需要 Linux root 环境；Windows 使用 WSL2 Ubuntu。构建 rootfs 和工作目录必须放在 WSL 原生 Linux 文件系统，下载缓存和最终产物可以位于 Windows 挂载盘。Ubuntu 构建依赖：

```sh
sudo apt-get install -y python3 python3-venv qemu-user-static binfmt-support \
  util-linux fdisk dosfstools e2fsprogs rsync libarchive-tools binutils \
  patchelf zstd xz-utils gzip tar kmod gdisk mtools
sudo /usr/lib/systemd/systemd-binfmt
cat /proc/sys/fs/binfmt_misc/qemu-aarch64
```

非 ARM 构建机必须看到处理器已 `enabled`，flags 包含 `F`。上述 systemd-binfmt 命令适用于提供 `/usr/lib/binfmt.d/qemu-aarch64.conf` 的 Ubuntu；旧发行版若通过 binfmt-support 注册，使用其 `update-binfmts --enable qemu-aarch64`，然后同样核查实际状态。

```sh
sudo python3 tools/build.py --variant xfce --work-dir /root/a7z-build/xfce
sudo python3 tools/build.py --variant cli --work-dir /root/a7z-build/cli
sudo python3 tools/build.py --variant kde --work-dir /root/a7z-build/kde
```

每个变体必须使用独立、全新的工作目录。Windows 可从 PowerShell 运行同样的 Python 命令，工具会转交给 WSL。默认 XFCE；`--plan` 只预览，`--resume` 只复用源锁、配方、变体和配置均相同的构建目录。失败后的目录保留，不递归删除用户目录；需要重新解包时选择新的工作目录。

流程依次为锁定源下载校验、独立 rootfs 解包、Arch 包安装、BSP/GPU/base 包生成、启动配置、公开镜像清理、两种镜像组装、压缩和审计。`--stop-after` 可停在明确阶段。可用 `--root-size-mib` 指定初始根分区大小；默认按内容估算。KDE 体积较大，应预留足够空间。

固定输入见 [config/sources.lock.json](config/sources.lock.json)：T5 内核 `6.6.98-4-aw2511`、配套 U-Boot 和官方 rootfs。`pacman -Syu` 使用滚动仓库，因此固定初始归档不代表以后逐字节重建；工具记录最终包版本、缓存 SHA256、构建配方和镜像哈希，供审计本次结果。

本项目不会把 Debian 的 `/usr/lib` 整体覆盖到 Arch。闭源/预编译 GPU 用户态放在私有目录，Arch Xorg 本体和 Mesa/libglvnd 保留；调用指定 GPU 路径时才使用 wrapper。进一步说明见 [GPU 使用文档](gpu/README.zh-CN.md)。第三方组件的许可证、来源和当前证据边界见 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)，不能将项目 MIT 许可证理解为第三方载荷已全部取得同样授权。

## 测试与源码导出

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m unittest discover -s packages/tests -p 'test_*.py' -v
python3 -m unittest discover -s gpu -p 'test_*.py' -v
python3 tools/export_source.py --plan
python3 tools/export_source.py --output out/source-release
```

镜像/安装器 loop 集成测试需要 Linux root 和明确的新测试目录；[Wi-Fi 镜像集成测试](tests/integration_personalize.py) 不需要 root 或设备访问。测试脚本生成的是测试夹具，不能用于启动开发板。

源码导出只复制明确白名单，缺文件、私密模式匹配或指向未导出记录的本地文档链接都会拒绝。目标必须是新目录；不导出开发仓库历史、SSH/串口私人 helper、实机记录、备份、下载缓存或二进制产物。导出目录自带源码 manifest 与 SHA256 清单。项目自身代码和文档采用 [MIT](LICENSE)；第三方组件单独遵循其许可证。
