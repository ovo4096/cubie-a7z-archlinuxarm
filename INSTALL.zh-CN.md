# 安装到 SD 或板载 UFS

本指南适用于 `v0.2.1-t5` 的 CLI、XFCE 和 KDE 镜像。UFS 的主要安装方式是**先从 SD 启动，在板上下载 UFS 镜像，解压后用 `dd` 写入整块 UFS**，与 [Radxa 官方 UFS 流程](https://docs.radxa.com/cubie/a7z/getting-started/install-system/ufs) 一致。项目安装器保留为第二选项。

## 1. 选择文件并准备首次联网

从 [v0.2.1-t5 发布页](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/tag/v0.2.1-t5) 下载：

| 文件名中的字段 | 用途 |
|---|---|
| `cli` | 命令行、SSH、维护；没有桌面、Chromium 或输入法 |
| `xfce` | XFCE + LightDM、Chromium（PowerVR）、Fcitx5 + Rime |
| `kde` | Plasma X11 + SDDM、Chromium（PowerVR）、Fcitx5 + Rime |
| `sd-512.img.zst` | 写入 SD 卡，镜像逻辑扇区为 512 字节 |
| `ufs-4096.img.zst` | 写入板载 UFS 的数据盘，镜像逻辑扇区为 4096 字节 |

两种介质镜像不能互换；改文件名或调整 `dd bs=` 不能转换其 GPT。每个镜像都需要对应的 `.img.sha256` 和 release 的 `SHA256SUMS`。前者验证解压后的原始镜像，后者可验证下载的压缩包与其他发行资产。

SD 系统本体建议使用至少 16 GB 的卡；要在 SD 中下载、解压并个性化 UFS 镜像，建议至少 32 GB。操作前用 `df -h` 确认下载目录的剩余空间，须同时容纳压缩包、原始镜像及可选的私人 Wi-Fi 副本。压缩包大小见发布页资产，原始镜像大小见对应 `.img.json` 的 `disk_bytes`。每份私人副本还需额外容纳一份完整原始镜像。

首次登录用户为 `alarm`，初始密码为 `alarm`；root 账号锁定。首次登录后运行 `passwd` 修改密码。首次启动会生成新的 SSH 主机密钥，不能沿用另一台设备的主机身份。

公开镜像不包含 Wi-Fi 密码、用户 SSH 公钥或预先生成的机器身份。无显示器安装前，按 [首次启动 Wi-Fi 向导](WIFI-FIRSTBOOT.zh-CN.md) 为已经校验的 `.img` 制作 `-private.img`，烧录这个私人副本。SD 与 UFS 是两个独立系统：**SD 的 Wi-Fi 配置不会随下载镜像自动转移到 UFS**。如需 UFS 首启自动联网，也要为 UFS 原始镜像创建自己的私人副本。

## 2. 安装并启动 SD 系统

下载所需 `sd-512.img.zst`、同名 `.img.sha256` 和 `SHA256SUMS` 到同一新目录。Linux 上的校验和解压示例：

```sh
sha256sum --ignore-missing -c SHA256SUMS
zstd -dk cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.zst
sha256sum -c cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.sha256
```

只在所有已下载项目校验成功后继续。完整清单也列出其他变体和原始镜像，`--ignore-missing` 允许只下载其中一组；它不会忽略已存在文件的校验失败。

Windows、macOS 或 Linux 可使用支持原始 `.img` 及写后校验的读卡器烧录工具，选择解压后的镜像和整张 SD 卡，与 [官方 microSD 安装步骤](https://docs.radxa.com/cubie/a7z/getting-started/install-system/microsd) 相同。需要预置 Wi-Fi 时改选前一步生成的 `-private.img`。

Linux 也可以用 `dd`，先用 `lsblk` 核对整张 SD 卡，并卸载该卡上已经挂载的分区。下面 `/dev/sdX` 必须替换为实际 SD 整盘设备，不能是电脑系统盘或 `/dev/sdX1` 分区：

```sh
lsblk -o NAME,SIZE,MODEL,TYPE,MOUNTPOINTS
sudo dd if=cubie-a7z-archlinuxarm-xfce-t5-sd-512.img of=/dev/sdX bs=4M conv=fsync status=progress
sync
```

在开发板断电时插卡，再上电。首次启动会扩展根分区并建立机器身份。可在本地桌面登录，或在路由器 DHCP 列表找到设备后通过 SSH 登录。安装 UFS 时，这个 SD 系统可以使用任何一个变体，无须与 UFS 的桌面变体相同。

## 3. 从 SD 下载 UFS 镜像

以下示例把 KDE 安装到 UFS。希望安装 XFCE 或 CLI 时，只把 `variant=kde` 改为 `xfce` 或 `cli`。在已经从 SD 启动的开发板终端中执行：

```sh
mkdir -p ~/a7z-ufs-v0.2.1
cd ~/a7z-ufs-v0.2.1
variant=kde
image="cubie-a7z-archlinuxarm-${variant}-t5-ufs-4096.img"
base='https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.1-t5'
df -h .
curl --fail --location --retry 3 --remote-name "$base/$image.zst"
curl --fail --location --retry 3 --remote-name "$base/$image.sha256"
curl --fail --location --retry 3 --remote-name "$base/SHA256SUMS"
sha256sum --ignore-missing -c SHA256SUMS
zstd -dk "$image.zst"
sha256sum -c "$image.sha256"
```

任一步下载、解压或校验失败时先处理错误，不要继续写盘。SD 下载目录需要同时容纳压缩包和解压镜像；具体大小见 release 资产与镜像 metadata。下载目录必须位于 SD 或其他独立存储，不能位于即将覆盖的 UFS 上。

本版预装 `curl`、`wget`、`zstd` 和 GPT 工具。旧 Arch SD 系统可以先完整更新并安装依赖：`sudo pacman -Syu --needed curl zstd gptfdisk`。如果使用官方 Debian SD 系统，则执行 `sudo apt update`，再执行 `sudo apt install curl zstd gdisk`。不要把官方示例中的 `.xz` 解压命令用于本项目的 `.zst` 文件。

需要 UFS 首次启动自动联网时，在此处按 [Wi-Fi 向导](WIFI-FIRSTBOOT.zh-CN.md) 创建 UFS 私人镜像，并把下文的 `image` 变量改为生成的 `ufs-4096-private.img` 路径。使用该私人镜像自己的 `.sha256` 验证；原始发布哈希不适用于已经注入 seed 的副本。

## 4. 核对 UFS 目标

**写入会覆盖目标 UFS 的分区和数据，已有数据需先备份。** 本板常见的数据盘为 `/dev/sda`，约 119 GiB、逻辑扇区 4096 字节；容量或设备名可能随型号和外设变化，必须现场核对。两个约 4 MiB 的 UFS boot LUN（本板通常为 `/dev/sdb`、`/dev/sdc`）不是安装目标，也不能写入 `/dev/sda1` 等单个分区。

```sh
findmnt -no SOURCE /
lsblk -o NAME,PATH,SIZE,MODEL,TYPE,LOG-SEC,MOUNTPOINTS
swapon --show
target=/dev/sda
sudo blockdev --getss "$target"
sudo blockdev --getsize64 "$target"
stat -c '%s' "$image"
readlink -f "/sys/class/block/${target##*/}/device"
```

确认当前根分区在 SD（例如 `/dev/mmcblk1p3`），目标是 UFS 整盘、扇区为 `4096`、容量大于镜像、没有挂载点或活动 swap。若还有 USB 磁盘，请结合型号与 sysfs 路径确认 UFS 控制器，不能只凭 `/dev/sda` 名称判断。**当前根位于 UFS 时必须关机，从 SD 重新启动，不能在运行中的 UFS 系统上覆盖自己。**

桌面文件管理器可能自动挂载 UFS 分区。关闭正在浏览目标盘的窗口，并对 `lsblk` 显示已经挂载的目标分区逐个执行 `sudo umount /dev/sdaN`（把 `N` 替换为实际分区号）。卸载失败时先解决占用，不使用强制或懒卸载绕过。重新运行 `lsblk` 和 `swapon --show`，确认目标整盘及所有子分区均未使用。

如希望让工具补充验证镜像布局、UFS 控制器、容量、挂载、swap 和设备占用，可以在实际 `dd` 前运行只读预览：

```sh
sudo a7z-install-ufs --image "$image" --target "$target" --dry-run
```

## 5. 用 dd 写入、回读并完成 GPT 调整

确认上一步全部满足后，在同一个终端执行：

```sh
sudo dd if="$image" of="$target" bs=4M conv=fsync status=progress
sync
sudo blockdev --flushbufs "$target"
sudo cmp --bytes="$(stat -c %s "$image")" "$image" "$target"
```

`dd` 必须成功完成；`cmp` 对刚写入的镜像字节范围进行完整回读比较，成功时没有输出、退出码为 `0`。如果出现差异、I/O 错误或非零退出码，不要继续启动，先检查镜像、供电和存储。回读范围按镜像长度截取，不要求 UFS 尾部未使用空间与某个文件一致。

**回读成功后**把备份 GPT 移到实际 UFS 末尾，再重新读取分区表：

```sh
sudo sgdisk -e "$target"
sudo blockdev --rereadpt "$target"
sudo udevadm settle
sudo sgdisk --verify "$target"
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$target"
sync
sudo poweroff
```

镜像通常小于 UFS，`sgdisk -e` 因而调整备份 GPT 的位置；它会改变 GPT 字节，所以整盘回读比较必须在它之前进行。首次启动扩容工具也能处理这一迁移，但手动安装推荐先完成上述验证。`sgdisk --verify` 不应报告 GPT 结构错误，分区应为 config / efi / rootfs 三项。此处没有把根分区手动扩满，首次 UFS 启动会自动扩展。

开发板完全关机后拔出 SD，再上电。从 UFS 登录后检查：

```sh
findmnt -no SOURCE /
lsblk -o NAME,SIZE,TYPE,MOUNTPOINTS
systemctl --failed
```

根分区应位于 UFS 数据盘，例如 `/dev/sda3`。首次扩容需要时间；详细日志可查看 `journalctl -b -u a7z-grow-root -u a7z-firstboot`。UFS 系统有自己新生成的 SSH 主机身份，首次连接应重新核对。

本板曾观察到无卡启动 UFS 后热插 SD 不识别。若需要再次从 SD 恢复，应关机后插卡再上电，而不是依赖热插拔。

## 第二选项：项目 UFS 安装器

同样先从 SD 启动、下载解压 UFS 镜像并准备私人副本，再执行：

```sh
sudo a7z-install-ufs --image "$image" --target "$target" --dry-run
sudo a7z-install-ufs --image "$image" --target "$target"
```

安装器要求输入完整目标确认文本，拒绝当前根盘、已挂载或活动 swap 设备、非 UFS 控制器、4 MiB boot LUN、错误扇区和不足容量；它完成整盘写入、完整回读与 GPT 迁移。可加 `--grow-root` 在安装阶段扩容，也可交给首次启动。成功后仍需关机、拔 SD、再上电。

在官方 Debian SD 系统中使用源码安装器，先安装 `python3 util-linux fdisk gdisk e2fsprogs`，再运行 `sudo python3 runtime/a7z-install-ufs ...`。安装器只接受原始 `.img`，不接受压缩包或 PhoenixSuit 专用固件。

## 桌面首次使用

XFCE 与 KDE 使用普通密码登录，没有自动登录。两种桌面预装 **Chromium（PowerVR）** 并将其设为默认网页入口；菜单或 `a7z-chromium` 均使用同一优化。正常退出所有浏览器实例后，`a7z-chromium --software` 可回退。查看 `chrome://gpu` 验证网页硬件绘制；当前 Chromium 的视频解码仍为 CPU，详见 [浏览器说明](gpu/CHROMIUM.zh-CN.md)。

XFCE/KDE 还预装 GStreamer 与 Cedar/OMX VPU 包，独立应用可通过 `a7z-vpu-run` 选择 H.264 硬解后端。已有实机验证来自 v0.2.0，本次未重测；它不会自动给 Chromium 增加视频硬解接口。CLI 未安装 VPU 包。运行方式见 [VPU 说明](vpu/README.zh-CN.md)。

中文输入使用 Fcitx5 + Rime「朙月拼音·简化字」，桌面登录后自动启动，初始英文，按 `Ctrl+Space` 切换中英文。输入拼音后按空格选字；第一次启用时 Rime 自动部署词典，可能短暂等待。图形会话使用 `zh_CN.UTF-8`，CLI/TTY 不强制中文。使用方式见 [中文桌面预设](desktop/README.zh-CN.md)；KDE 的 Vulkan 配置与回退见 [KDE 说明](KDE.zh-CN.md)。日常完整更新前阅读 [滚动升级说明](ROLLING-UPGRADE.zh-CN.md)。
