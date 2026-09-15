# v0.2.0-t5：中文桌面、预装 Chromium 与 SD → UFS 安装

本版为 Radxa Cubie A7Z 提供 CLI、XFCE、KDE 三种环境，各有 SD 与 UFS 两种整盘镜像，使用锁定的官方 T5 / Trixie BSP、内核 `6.6.98-4-aw2511` 与配套 PowerVR 用户态。

**桌面版预装 Chromium（PowerVR）与 Fcitx5 + Rime。网页 GPU 渲染已适配，Chromium 内视频硬件解码仍未完成。** KDE 继续采用已验证的 Plasma/SDDM Vulkan 界面路径，KWin X11 合成保持关闭。请按下表选择环境，并阅读各项验证范围。

六个最终镜像均完成构建、只读清理审计和压缩流完整性校验。CLI SD、XFCE SD 与 KDE UFS 分别进行实机验收；其余三个文件未单独上板启动。下文引用的历史测试用于说明配置依据，本版最终文件的验收范围见末尾验证表。

## 选择镜像与本版优化

| 环境 | 本版配置 | 适用场景与边界 |
|---|---|---|
| CLI | SSH、NetworkManager、蓝牙命令行、BSP 维护与 GPU 诊断；预装下载、解压、GPT 工具 | 无显示器系统、服务、开发或作为 UFS 安装用 SD；没有 Xorg、浏览器、Rime 或 VPU 包 |
| XFCE | XFCE + LightDM；Arch Xorg 的 PowerVR glamor；xfwm4 XRender 合成与 XPresent；预装 Chromium Vulkan/ANGLE 启动器、中文字体、Fcitx5 + Rime、GStreamer/Cedar VPU 包 | 较轻的中文桌面；网页合成、Canvas、栅格化、WebGL 走 GPU，浏览器视频解码仍使用 CPU；VPU 供独立 GStreamer 使用 |
| KDE | Plasma X11 + SDDM；PowerVR glamor；SDDM/Plasma Qt Quick 界面使用 PowerVR Vulkan；同一 Chromium 优化、中文字体、Fcitx5 + Rime、GStreamer/Cedar VPU 包；Dolphin、Konsole、Kate、Ark 与音频/网络管理 | 更完整的桌面工具；保留稳定登录与软件回退，关闭会触发 T5 EGL 崩溃的 KWin 合成，因此不提供依赖合成的桌面特效 |

| 下载 | SD 卡镜像 | 板载 UFS 镜像 |
|---|---|---|
| CLI | [CLI SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-cli-t5-sd-512.img.zst) | [CLI UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-cli-t5-ufs-4096.img.zst) |
| XFCE | [XFCE SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.zst) | [XFCE UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-xfce-t5-ufs-4096.img.zst) |
| KDE | [KDE SD](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-kde-t5-sd-512.img.zst) | [KDE UFS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/cubie-a7z-archlinuxarm-kde-t5-ufs-4096.img.zst) |

校验文件和逐项构建/清理记录随发布页 Assets 提供，包括 [SHA256SUMS](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/SHA256SUMS) 与 [最终镜像硬件测试摘要](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5/hardware-validation.json)。请从同一发布页下载镜像及对应记录，先校验再写入。

两种桌面的默认网页入口均为 **Chromium（PowerVR）**，使用原版 Arch Chromium 软件包，保留原 `Chromium` 菜单项用于对照和回退。图形登录使用 `zh_CN.UTF-8`；CLI/TTY 不强制中文，避免文本控制台缺字。输入法为 Fcitx5 + Rime「朙月拼音·简化字」，初始英文，按 `Ctrl+Space` 切换中英文。第一次启用 Rime 时会自动部署词典，可能需要短暂等待；通过 Fcitx5 配置工具可调整输入法，Rime 的方案选单可用 `F4` 或 `` Ctrl+` `` 打开。预设不携带用户学习词库、同步身份或浏览记录。框架选择依据 [Rime 中文维基](https://wiki.archlinuxcn.org/wiki/Rime) 与 [Fcitx5 配置文档](https://fcitx-im.org/wiki/Setup_Fcitx_5/zh-cn)。

文件名格式：

```text
cubie-a7z-archlinuxarm-{cli|xfce|kde}-t5-sd-512.img.zst
cubie-a7z-archlinuxarm-{cli|xfce|kde}-t5-ufs-4096.img.zst
```

SD 使用 512 字节逻辑扇区，UFS 使用 4096 字节。**两种镜像不可互换，改名或改变 `dd bs=` 无法转换 GPT。** 首次启动自动扩展根分区；每份镜像有自己的 UUID、校验文件与构建记录。旧 `v0.1.0-t5` 镜像和 `v0.1.1-gpu-preview` 增量资产保留，本版作为新的发行资产提供。

## 安装 SD 系统

SD 系统本体建议使用至少 16 GB 的卡；如果还要在 SD 中下载、解压并个性化 UFS 镜像，建议至少 32 GB，并先用 `df -h` 核对可用空间。下载目录须同时容纳压缩包与原始镜像；大小分别见发布页资产与 `.img.json` 的 `disk_bytes`。另生成私人 Wi-Fi 副本时还需再保存一份原始镜像大小的文件。

下载所需 `sd-512.img.zst`、同名 `.img.sha256` 和本 release 的 `SHA256SUMS` 到一个新目录。Linux 校验示例：

```sh
sha256sum --ignore-missing -c SHA256SUMS
zstd -dk cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.zst
sha256sum -c cubie-a7z-archlinuxarm-xfce-t5-sd-512.img.sha256
```

必须所有已下载文件校验成功后再继续。`--ignore-missing` 允许只下载六种镜像中的一组，不会忽略已存在文件的校验失败。Windows/macOS/Linux 使用读卡器及支持原始 `.img` 的烧录工具，把解压后的镜像写入整张 SD 卡并完成写后校验；断电插卡，再上电。[官方 SD 步骤](https://docs.radxa.com/cubie/a7z/getting-started/install-system/microsd)也采用这种方式。

无显示器使用前，按 [烧录前 Wi-Fi 指南](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/WIFI-FIRSTBOOT.zh-CN.md)为原始镜像生成 `-private.img`，改为烧录这份私人副本。公开文件不会被写入密码。首次启动从 config 分区导入连接后删除 seed，但原私人镜像与已经联网的系统仍包含网络凭据，不能作为公开镜像再分发。

初始用户/密码为 `alarm` / `alarm`，root 锁定，没有自动登录。首次登录后执行 `passwd`。SSH 主机密钥在首次启动生成；可从路由器 DHCP 客户端列表找到设备并核对新主机身份。

## 主要方式：在 SD 系统中下载 UFS 镜像，再用 dd 安装

这与 [Radxa 官方 UFS 安装方法](https://docs.radxa.com/cubie/a7z/getting-started/install-system/ufs)一致：**先从 SD 正常启动，下载并解压 UFS 镜像，核对目标盘，再写入板载 UFS。** SD 可使用任意变体，不要求与要安装的 UFS 桌面一致。写入会覆盖 UFS，先备份已有数据；不要从正在运行的 UFS 系统覆盖自己。

以下在开发板的 SD 系统终端操作，以 KDE UFS 为例。若需要其他版本，修改 `variant`：

```sh
mkdir -p ~/a7z-ufs-v0.2.0
cd ~/a7z-ufs-v0.2.0
variant=kde
image="cubie-a7z-archlinuxarm-${variant}-t5-ufs-4096.img"
base='https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases/download/v0.2.0-t5'
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

`sgdisk -e` 将备份 GPT 从镜像末尾移到真实 UFS 末尾，改变 GPT 字节，因此不能放在原始镜像回读比较之前。根分区由首次启动自动扩容。关机后拔掉 SD，再上电；登录后用 `findmnt -no SOURCE /` 确认根位于 UFS（例如 `/dev/sda3`）。完整说明和恢复检查见 [安装指南](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/INSTALL.zh-CN.md)。

本板曾观察到无卡启动 UFS 后热插 SD 不识别，需要 SD 恢复时应关机插卡再上电。

## 第二选项：项目 UFS 安装器

同样先从 SD 启动，使用上面下载解压、校验过的 UFS 镜像：

```sh
sudo a7z-install-ufs --image "$image" --target "$target" --dry-run
sudo a7z-install-ufs --image "$image" --target "$target"
```

第二条要求输入完整的目标确认文本。安装器检查 UFS 控制器、扇区、容量、当前根/挂载/swap/设备占用，拒绝 4 MiB boot LUN；随后自动写入、完整回读和迁移 GPT。`--grow-root` 可提前离线扩容，不加则由首次启动完成。成功后关机、拔 SD、再上电。官方 Debian SD 可安装 `python3 util-linux fdisk gdisk e2fsprogs` 后运行仓库的 `runtime/a7z-install-ufs`。两种方式都只使用原始整盘 `.img`。

## GPU、视频和桌面回退

桌面菜单选择 **Chromium（PowerVR）** 或运行 `a7z-chromium`。默认参数为 X11 + ANGLE Vulkan，并选择私有 PowerVR ICD 和 Chromium 的三个 Vulkan feature；不关闭沙箱、不修改系统 Mesa/GLVND、不预加载私有 EGL 库。`chrome://gpu` 用于查看实际网页绘制后端。正常退出所有 Chromium 实例后，`a7z-chromium --software` 可明确回退软件绘制；同一浏览器 profile 的已运行进程不会因再次点击另一个入口自动换后端。

此前 XFCE 系统的受控短测中，1920×1080 页面 48 个半透明 CSS 动画元素的平均 `requestAnimationFrame` 间隔从 28.26 ms 降到 16.67 ms，进程 CPU 从约 154% 降到 110%（单核为 100%）。这是历史系统中特定合成页面的回调时序与 CPU，不能外推为所有网页帧率、KDE 性能或本版最终镜像的结果。详见 [XFCE / Chromium 实测](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/gpu/XFCE-CHROMIUM-VALIDATION.zh-CN.md)。

Chromium 播放 H.264 的已有媒体记录为 `FFmpegVideoDecoder`、`kIsPlatformVideoDecoder=false`，本版尚未接入浏览器视频硬解。本版 XFCE/KDE 预装 Cedar/OMX VPU 包和 GStreamer，CLI 未预装；`a7z-vpu-run` 为独立应用选择 Cedar H.264 硬解后端。该后端的硬件解码和窗口显示已有实测，具体片段、帧数及丢帧情况见 [VPU 验收](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/vpu/VALIDATION.zh-CN.md)，本版最终文件另列验收结果。安装 VPU 包、查看 GPU 利用率或添加通用 VA-API flags 都不能补齐 Chromium 通往 Cedar 的接口，详见 [视频接口工作](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/vpu/CHROMIUM-INTEGRATION.zh-CN.md)。

KDE 默认关闭 KWin 合成，Plasma/SDDM 的 Qt Quick Vulkan 渲染和 Xorg glamor 独立生效。GLX/AIGLX 仍是软件路径；Wayland、游戏、所有桌面特效及所有视频编码格式均未因此得到验证。KDE 软件回退步骤见 [KDE 文档](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/KDE.zh-CN.md)。

启动器没有添加关闭沙箱的参数，但已有 Chromium 测试中，`chrome://sandbox` 的命名空间和 Seccomp-BPF/TSYNC 已启用时，GPU 信息仍可能报告 `sandboxed=false`。因此不能宣称 GPU 进程也受沙箱保护；最终测试应同时记录这两处状态。

KDE 还为交流供电设置了不自动休眠的系统默认值，避免开发板无人操作时因桌面节能策略停止网络服务。用户仍可在电源管理中自行调整；显示器熄屏、锁屏和手动休眠是独立设置。T5 的休眠恢复尚未完成实机验收，不能把自动休眠关闭理解为已经修复了内核恢复路径。

## 验证、升级与镜像清理

本版使用 `radxa-a7z-gpu-kmod 0.1.0_3-3`、GPU 用户态包 `24.2.6603887_t5-7` 和 `radxa-a7z-base 0.1.0-4`。GPU 模块从锁定的 T5 DKMS 源码编译，修复原模块在读取尚无私有连接的 DRM fdinfo 时触发空指针崩溃的问题：保留标准 DRM 信息，省略依赖私有连接的 PowerVR 统计字段，渲染接口与 T5 固件保持原样。[修复说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/gpu/kernel/README.md)列出源码、补丁与构建验证范围；实机查询、桌面及重启回归见下表，不能由源码测试推定所有驱动路径均已稳定。

模块使用 T5 内核支持的 XZ CRC32 校验与 1 MiB LZMA2 字典。此前候选的 CRC64 压缩会被内核拒绝，相关候选镜像已排除；本版需验证实际安装文件的压缩格式和首次启动后的模块身份，不能只以解压后的 ELF 相同作为通过依据。

构建记录中的 `input_reuse` 表示复用构建机上同变体、已净化的中间根文件系统，然后重新执行完整 Arch 更新、全部板级软件包构建和安装、系统配置、清理及整盘镜像生成。本轮没有重新解包 Arch 初始 tar，也没有从测试板导入系统或个人数据；复用来源与实际执行阶段均记录哈希。

本轮 140 项离线测试通过。六张最终镜像均有只读 rootfs/config/EFI/initramfs 审计、原始镜像 SHA256、压缩包 SHA256 及完整解压后的字节数/SHA256 记录；离线检查与板上启动分别列出。

| 本版镜像 | 构建、清理与完整性审计 | 该文件的实机结果 |
|---|---|---|
| CLI SD | 构建、两层清理审计与压缩完整性通过 | 完整写后回读、首次启动/扩容/Wi-Fi、完整更新及普通重启通过；GPU 模块自动加载并匹配修复版本 |
| CLI UFS | 构建、两层清理审计与压缩完整性通过 | 未单独实机启动 |
| XFCE SD | 构建、两层清理审计与压缩完整性通过 | 完整写后回读、首启/扩容/Wi-Fi、LightDM 登录、更新与图形库重装、WebGL 与 Chromium/Mousepad 中文输入、fdinfo、视频与普通重启后的图形复测通过 |
| XFCE UFS | 构建、两层清理审计与压缩完整性通过 | 未单独实机启动 |
| KDE SD | 构建、两层清理审计与压缩完整性通过 | 未单独实机启动 |
| KDE UFS | 构建、两层清理审计与压缩完整性通过 | 完整写后回读、首启/扩容/Wi-Fi、SDDM 登录、更新与图形库重装、WebGL 与中文输入、fdinfo/转储回归、16 分钟空闲/解锁、注销及重启后图形复测通过；UFS 由串口选择，未单独验证拔卡冷启动 |

硬件记录包括首次启动与扩容、GPU fdinfo 查询、桌面渲染和中文输入、视频解码器、空闲/解锁、注销与重启，以及完整升级事务后的复测。未单独启动的文件标为“未单独实机启动”；另一介质或历史版本的通过不计入该文件的结果。

两种桌面在更新后均实际输入「你好世界」：Chromium 输入框，以及 XFCE 的 Mousepad / KDE 的 Kate 编辑器；编辑器还验证了 UTF-8 保存内容。两种桌面的 Chromium WebGL 1/2 均使用 PowerVR，并通过实际像素读回。浏览器的命名空间、Seccomp-BPF 与 TSYNC 启用，但 GPU 信息仍为 `sandboxed=false`。

本版两种桌面各自完成本地 15 秒、450 帧 H.264 1080p30 样片：Chromium 均为 `FFmpegVideoDecoder`、`kIsPlatformVideoDecoder=false`，450 帧且未报告丢帧；独立 GStreamer `omxh264dec` 路径也各输出 450 帧、0 丢帧，Cedar 中断各增加 450。独立路径协商为 SystemMemory YV12 1920×1088；这些结果不证明裁剪元数据、音频质量、零拷贝、其他编码格式或网页视频硬解。

1920×1080 的受控 CSS 动画短测中，XFCE 的 600 个测量样本平均间隔为 16.69 ms、95 分位为 16.7 ms，Chromium 进程 CPU 约 109%；KDE 的 601 个样本平均为 16.67 ms、95 分位为 16.8 ms，CPU 约 116%（单核计 100%）。这是特定页面的回调时序和进程 CPU，不能视为所有网页、整套桌面的帧率或与其他系统的等条件比较。

日常采用完整 `sudo pacman -Syu`，不要做局部升级。已有检查覆盖完整更新事务、同版本核心图形包重装、驱动文件哈希与真实图形复测；这不保证未来任意 Arch、Chromium、Mesa、Qt 或 Plasma 版本都兼容 T5 私有驱动。KDE X11 的上游维护期限也要求后续单独验证迁移路线。详细维护和恢复步骤见 [滚动升级说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/ROLLING-UPGRADE.zh-CN.md)。

公开镜像要求清除 Wi-Fi、网络 seed、SSH 私钥、固定机器身份、浏览器 profile、用户词库、构建缓存和个人文件，并在首启生成本机身份。只保留经审核的系统预设和 `/etc/skel` 模板。镜像清理、只读挂载审计、完整 SHA256 与压缩解压回读的结果应随资产提供；这些检查与实际硬件启动分别记录。[清理规则](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/RELEASE-HYGIENE.zh-CN.md)。

项目源码采用 MIT；内核、U-Boot、固件、Arch 包及 GPU/VPU 用户态分别受各自上游许可约束。第三方来源与现有证据见 [许可说明](https://github.com/ovo4096/cubie-a7z-archlinuxarm/blob/v0.2.0-t5/THIRD-PARTY-LICENSES.zh-CN.md)，镜像实际包版本、构建来源和哈希以此 release 附带记录为准。
