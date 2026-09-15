# v0.2.2-t5：共用 HDMI 内核修复

本版为 Radxa Cubie A7Z 的 CLI、XFCE 和 KDE 加入同一 HDMI 内核修复，解决已定位的 HPD 断连后输出状态不一致问题，移除旧桌面启动兜底。保留真实连接检测，不限定显示器型号或固定分辨率。提供三个变体各自的 SD / UFS 六种镜像，继续使用锁定的官方 T5 / Trixie BSP。

**本次新包、六张新镜像及 KDE / XFCE 未运行新的自动化测试、滚动升级回归或实机测试。** 此前同一内核补丁已在 CLI 测试机完成两次启动和一次同屏实际 HDMI 拔插，均在旧兜底禁用、`hpd_mask=0` 条件下由用户确认画面正常。这是限定范围的既有验证，不能作为本版六个新文件或多型号显示器已通过验收的结论。

## 本次修改

内核包更新为 `linux-radxa-a7z 6.6.98_4-2`，保留内核 release `6.6.98-4-aw2511`，加入 HDMI 驱动补丁。原驱动在 HPD 拔出路径直接关闭发送端并清空模式，DRM 的 CRTC 却仍可处于活动状态；重新连接后若没有新模式提交，输出就无法恢复。新补丁让原有 atomic enable / disable 和电源管理回调负责输出状态，避免这条状态错配路径，同时保留 HPD、EDID 和连接通知。

`radxa-a7z-base 0.1.0-6` 固定依赖该内核包，删除旧 `/usr/bin/a7z-hdmi-compat`，迁移 LightDM / SDDM 的 `95-a7z-hdmi-compat.conf`。精确的项目配置直接删除；有用户增补时，只删除原样的项目命令，其余设置保留；未知自定义旧命令会报告并要求人工处理。`70-a7z-desktop.conf` 和 GPU / Vulkan 配置保留，SDDM 在没有其他用户覆盖时恢复默认 Xsetup / Xstop。迁移不访问运行中的 HPD，也不重启桌面，升级后应重启进入新内核。

**这不是所有 HDMI 场景的完整修复。** 更换显示器、无屏启动后连接、SCDC 重新配置和休眠恢复尚未验证；CLI 没有因此获得完整的自动模式选择能力。移除 HPD 关闭调用也移除了其中隐含的 HDCP disable，受保护视频断连后的认证 / 重新认证需另行处理，不能借用普通 CLI 的验证结果。详见 [HDMI 修复及迁移说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/desktop/HDMI.zh-CN.md)。

本版没有 USB 修复，没有新增 GPU 或浏览器视频硬解功能。配套板级包更新依赖以匹配新内核；GPU / VPU 载荷、Chromium、Rime 及桌面配置继续使用既有 T5 快照，未在打包时执行滚动升级。发布页同时提供配套软件包和 [内核输入包](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/a7z-hdmi-kernel-input-v0.2.2-t5.tar.gz)，源码构建方法见 [内核说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/kernel/hdmi/README.md)。

## 选择镜像

| 环境 | 预装配置 | 适用场景与边界 |
|---|---|---|
| CLI | 共用 HDMI 内核修复；SSH、NetworkManager、蓝牙命令行、BSP 维护，以及下载、解压和 GPT 工具 | 无显示器运行、服务、开发或作为 UFS 安装用 SD；没有桌面、浏览器或 Rime |
| XFCE | 共用 HDMI 内核修复；XFCE + LightDM；PowerVR glamor、XRender / XPresent 合成；Chromium（PowerVR）、中文字体、Fcitx5 + Rime、GStreamer / Cedar VPU 包 | 较轻的中文桌面；网页 GPU 渲染与独立 GStreamer H.264 硬解沿用原有配置，Chromium 内视频仍由 CPU 解码 |
| KDE | 共用 HDMI 内核修复；Plasma X11 + SDDM；PowerVR glamor、Qt Quick Vulkan；同一 Chromium 与中文输入配置；Dolphin、Konsole、Kate、Ark 和音频/网络管理 | 更完整的桌面工具；KWin 合成保持关闭，不提供依赖合成的桌面特效 |

| 下载 | SD 卡镜像 | 板载 UFS 镜像 |
|---|---|---|
| CLI | [CLI SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-cli-t5-sd-512.img.zst) | [CLI UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-cli-t5-ufs-4096.img.zst) |
| XFCE | [XFCE SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.zst) | [XFCE UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-xfce-t5-ufs-4096.img.zst) |
| KDE | [KDE SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-kde-t5-sd-512.img.zst) | [KDE UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/cubie-a7z-archlinuxarm-kde-t5-ufs-4096.img.zst) |

请从本发布页下载镜像、对应 `.img.sha256`、[SHA256SUMS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/SHA256SUMS) 和构建记录，先校验再写入。测试状态单独记录在 [validation-status.json](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5/validation-status.json)，标记为未运行。SD 使用 **512 字节**逻辑扇区，UFS 使用 **4096 字节**；两种镜像不可互换，改名或改变 `dd bs=` 无法转换 GPT。首次启动自动扩展根分区。

两种桌面的默认网页入口为 **Chromium（PowerVR）**，另保留普通 Chromium 入口供回退。图形会话预设简体中文，CLI / TTY 不强制中文。输入法采用 Fcitx5 + Rime「朙月拼音·简化字」，初始英文，按 **Ctrl+Space** 切换中英文；首次启用需要部署词典。公开镜像不包含用户学习词库或浏览记录。

## 安装 SD 系统

SD 系统本体建议使用至少 16 GB 的卡；如果还要在 SD 中下载、解压并个性化 UFS 镜像，建议至少 32 GB，并先用 `df -h` 核对可用空间。下载目录须同时容纳压缩包与原始镜像；大小分别见发布页资产与 `.img.json` 的 `disk_bytes`。另生成私人 Wi-Fi 副本时还需再保存一份原始镜像大小的文件。

下载所需 `sd-512.img.zst`、同名 `.img.sha256` 和本 release 的 `SHA256SUMS` 到一个新目录。Linux 校验示例：

```sh
sha256sum --ignore-missing -c SHA256SUMS
zstd -dk cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.zst
sha256sum -c cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.sha256
```

必须所有已下载文件校验成功后再继续。`--ignore-missing` 允许只下载六种镜像中的一组，不会忽略已存在文件的校验失败。Windows/macOS/Linux 使用读卡器及支持原始 `.img` 的烧录工具，把解压后的镜像写入整张 SD 卡并完成写后校验；断电插卡，再上电。[官方 SD 步骤](https://docs.radxa.com/cubie/a7z/getting-started/install-system/microsd)也采用这种方式。

无显示器使用前，按 [烧录前 Wi-Fi 指南](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/WIFI-FIRSTBOOT.zh-CN.md)为原始镜像生成 `-private.img`，改为烧录这份私人副本。公开文件不会被写入密码。首次启动从 config 分区导入连接后删除 seed，但原私人镜像与已经联网的系统仍包含网络凭据，不能作为公开镜像再分发。

初始用户/密码为 `alarm` / `alarm`，root 锁定，没有自动登录。首次登录后执行 `passwd`。SSH 主机密钥在首次启动生成；可从路由器 DHCP 客户端列表找到设备并核对新主机身份。

## 主要方式：在 SD 系统中下载 UFS 镜像，再用 dd 安装

这与 [Radxa 官方 UFS 安装方法](https://docs.radxa.com/cubie/a7z/getting-started/install-system/ufs)一致：**先从 SD 正常启动，下载并解压 UFS 镜像，核对目标盘，再写入板载 UFS。** SD 可使用任意变体，不要求与要安装的 UFS 桌面一致。写入会覆盖 UFS，先备份已有数据；不要从正在运行的 UFS 系统覆盖自己。

以下在开发板的 SD 系统终端操作，以 KDE UFS 为例。若需要其他版本，修改 `variant`：

```sh
mkdir -p ~/a7z-ufs-v0.2.2
cd ~/a7z-ufs-v0.2.2
variant=kde
image="cubie-a7z-archlinuxarm-${variant}-t5-ufs-4096.img"
base='https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.2-t5'
df -h .
curl --fail --location --retry 3 --remote-name "$base/$image.zst"
curl --fail --location --retry 3 --remote-name "$base/$image.sha256"
curl --fail --location --retry 3 --remote-name "$base/SHA256SUMS"
sha256sum --ignore-missing -c SHA256SUMS
zstd -dk "$image.zst"
sha256sum -c "$image.sha256"
```

每步成功后再继续。SD 必须有同时保存压缩包与原始镜像的空间，下载目录不能在即将写入的 UFS。新镜像已预装下载、解压和 GPT 工具；旧 Arch 系统可执行 `sudo pacman -Syu --needed curl zstd gptfdisk`，官方 Debian SD 则使用 `sudo apt update` 和 `sudo apt install curl zstd gdisk`。

**SD 的 Wi-Fi 不会自动复制到 UFS。** 如需 UFS 首启无显示器联网，此时为 UFS `.img` 再生成自己的私人副本，并把下文 `image` 改成该 `ufs-4096-private.img` 路径；校验使用私人副本自己的 `.sha256`。

核对当前根设备与目标：

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

当前根应在 SD，例如 `/dev/mmcblk1p3`。目标必须是 UFS **整盘**，逻辑扇区为 `4096`，容量大于镜像且未使用；本板常见为约 119 GiB 的 `/dev/sda`。不要选择 `/dev/sda1` 等分区，也不要选择约 4 MiB 的 `/dev/sdb`、`/dev/sdc` boot LUN。设备名可能变化，尤其连接 USB 磁盘后，应同时核对型号、容量及 UFS 的 sysfs 控制器路径。

若桌面已自动挂载 UFS，关闭文件管理器中对应窗口，对 `lsblk` 显示已挂载的每个目标分区执行 `sudo umount /dev/sdaN`（替换实际分区号），再检查 `lsblk` 与 `swapon --show`。目标及其子分区不能有挂载点、活动 swap 或其他占用。需要自动补充检查时，可运行只读 `sudo a7z-install-ufs --image "$image" --target "$target" --dry-run`。

确认目标后写入并完整回读：

```sh
sudo dd if="$image" of="$target" bs=4M conv=fsync status=progress
sync
sudo blockdev --flushbufs "$target"
sudo cmp --bytes="$(stat -c %s "$image")" "$image" "$target"
```

`dd` 必须成功完成；`cmp` 比较完整镜像字节范围，成功无输出、退出码为 `0`。出现差异或 I/O 错误时停止，先检查存储与供电。**仅在回读成功后**迁移备份 GPT，再验证分区表：

```sh
sudo sgdisk -e "$target"
sudo blockdev --rereadpt "$target"
sudo udevadm settle
sudo sgdisk --verify "$target"
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS "$target"
sync
sudo poweroff
```

`sgdisk -e` 将备份 GPT 从镜像末尾移到真实 UFS 末尾，改变 GPT 字节，因此不能放在原始镜像回读比较之前。根分区由首次启动自动扩容。关机后拔掉 SD，再上电；登录后用 `findmnt -no SOURCE /` 确认根位于 UFS（例如 `/dev/sda3`）。完整说明和恢复检查见 [安装指南](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/INSTALL.zh-CN.md)。

本板曾观察到无卡启动 UFS 后热插 SD 不识别，需要 SD 恢复时应关机插卡再上电。

## 第二选项：项目 UFS 安装器

同样先从 SD 启动，使用上面下载解压、校验过的 UFS 镜像：

```sh
sudo a7z-install-ufs --image "$image" --target "$target" --dry-run
sudo a7z-install-ufs --image "$image" --target "$target"
```

第二条要求输入完整的目标确认文本。安装器检查 UFS 控制器、扇区、容量、当前根/挂载/swap/设备占用，拒绝 4 MiB boot LUN；随后自动写入、完整回读和迁移 GPT。`--grow-root` 可提前离线扩容，不加则由首次启动完成。成功后关机、拔 SD、再上电。官方 Debian SD 可安装 `python3 util-linux fdisk gdisk e2fsprogs` 后运行仓库的 `runtime/a7z-install-ufs`。两种方式都只使用原始整盘 `.img`。

## 已安装 v0.2.1：使用配套包升级

先备份系统并保留 SD 恢复卡，再从本发布页下载并校验配套内核、base、无线、GPU 及已安装的 VPU 包，在同一次 `pacman -U` 事务中更新。不要只替换 Image 或绕过依赖。升级会清理原版桌面 95 HDMI 钩子，保留 GPU 配置；有用户自定义旧命令时先按迁移提示处理，然后重启进入新内核。准确包清单和命令见 [维护与升级说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/ROLLING-UPGRADE.zh-CN.md#从标准-v021-升级板级包)。本次升级过程没有进行额外测试。

内核 release 未改变，旧默认启动标签仍可能指向被新包替换的同名文件；它不是自动保留旧内核的保证。当前系统备份不能由既有自动启动快照代替。

## 保留的 GPU、视频与桌面设置

桌面菜单选择 **Chromium（PowerVR）** 或运行 `a7z-chromium`，使用 X11 + ANGLE Vulkan 与私有 PowerVR ICD。启动器不修改系统 Mesa / GLVND，不预加载私有 EGL 库。退出所有 Chromium 实例后，可用 `a7z-chromium --software` 回退软件绘制；同一 profile 已有运行进程时，再开另一入口不会自动切换后端。

**网页 GPU 加速不等于视频硬件解码。** v0.2.0 的 Chromium 媒体记录使用 `FFmpegVideoDecoder`，`kIsPlatformVideoDecoder=false`；本版没有改变这条路径。XFCE / KDE 预装的 Cedar / OMX 与 GStreamer 可通过 `a7z-vpu-run` 提供独立 H.264 硬解，不能靠通用 VA-API 参数自动接入 Chromium。历史依据见 [v0.2.0 网页绘制记录](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md) 和 [v0.2.0 VPU 记录](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/vpu/VALIDATION.zh-CN.md)，均不是本次新镜像测试。

KDE 继续采用 Plasma X11：SDDM / Plasma 的 Qt Quick 使用 PowerVR Vulkan，Xorg 使用 glamor，KWin 合成关闭。GLX / AIGLX 仍是软件路径，Wayland 未适配。交流供电默认不自动休眠，避免无人操作时网络服务随桌面休眠中断；这并不表示 T5 的休眠恢复问题已经修复。回退步骤见 [KDE 说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/KDE.zh-CN.md)。

## 打包来源、测试范围与维护

本版复用构建机上三个变体各自的干净离线 rootfs 和既有 T5 包快照，复制到新构建卷后安装带 HDMI 补丁的内核、base `0.1.0-6` 及匹配依赖的板级包，并移除旧桌面 HDMI 钩子。随后执行公开镜像清理，重新生成带独立 UUID 的六张 SD / UFS 镜像；原始输入保持不变。

本次没有从开发板复制运行中的系统、Wi-Fi、用户目录或个人数据，也没有执行 `pacman -Syu`。三个变体共用同一内核修复；浏览器、输入法和图形功能配置沿用原快照。具体输入哈希、修改文件、包版本与产物哈希以随资产提供的构建记录为准。

| v0.2.2 镜像 | 自动化 / 回归测试 | 此新文件的实机启动 |
|---|---|---|
| CLI SD / CLI UFS | 未运行 | 未运行 |
| XFCE SD / XFCE UFS | 未运行 | 未运行 |
| KDE SD / KDE UFS | 未运行 | 未运行 |

本次只进行修复、打包和发布，没有开展额外测试。打包过程生成的 SHA256、文件清单和输入来源记录用于确认文件身份，不代表启动、桌面或滚动升级已通过验证。此前 CLI 补丁确认及 v0.2.0 测试报告仅是限定范围的历史记录，不能作为 v0.2.2 六张新镜像的验收结论。

公开镜像继续采用原有清理规则：不携带 Wi-Fi 密码、网络 seed、SSH 私钥、固定机器身份、浏览器 profile、Rime 用户词库或个人文件；身份在首次启动生成。请勿将已经联网或个性化的 `-private.img` 重新发布。规则见 [镜像清理说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/RELEASE-HYGIENE.zh-CN.md)。

日常使用完整 `sudo pacman -Syu`，不要局部升级。此前版本的更新结果不保证未来 Arch、Chromium、Mesa、Qt 或 Plasma 与 T5 私有驱动持续兼容，本次也未做滚动升级测试；维护与恢复方法见 [滚动升级说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/ROLLING-UPGRADE.zh-CN.md)。

项目自身源码采用 MIT；内核、U-Boot、固件、Arch 包及 GPU / VPU 用户态各自遵循上游许可。来源和现有证据见 [第三方许可说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.2-t5/THIRD-PARTY-LICENSES.zh-CN.md)。
