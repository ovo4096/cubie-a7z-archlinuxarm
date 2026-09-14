# cubie-a7z-archlinuxarm 发行说明

本项目为 Radxa Cubie A7Z 提供基于官方 T5 / Trixie BSP 的 Arch Linux ARM。发布渠道为 [GitHub Releases](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases)，具体下载项、文件哈希与验证状态以各 release 为准。

| 变体 | SD / 512 字节 | UFS / 4096 字节 |
|---|---|---|
| CLI | 已实机验证首次启动、联网、扩容、更新与 GPU 探针 | 镜像清理/哈希通过，未单独实机启动 |
| XFCE + LightDM | 已实机验证 | 同 BSP 先前镜像已实机验证 |
| KDE Plasma X11 + SDDM | 镜像清理/哈希通过，未单独实机启动 | 启动、首启联网、SDDM/Plasma 正常登录及 Vulkan 界面渲染通过；最终配置在同一 UFS 系统复测 |

XFCE 的 SD 与 UFS 均已验证 T5 `6.6.98-4-aw2511` 启动、实际根分区、Wi-Fi/SSH、首次扩容、LightDM 正常登录和完整 2560×1440 桌面。UFS 完成过拔 SD 冷启动；SD 与 UFS 镜像使用不同 UUID。该结论来自先前同 BSP 的实机验证，不自动覆盖未来所有镜像版本、外设或长期负载。

本次清理后的 XFCE SD 发行镜像也经私人 Wi-Fi 副本完整写入/回读后重做首启验证：实际根 UUID 与发行 metadata 一致，自动联网、扩容、seed 导入后删除、机器身份及 SSH/pacman 密钥重新生成均通过；EGL/GLES 硬件绘制、LightDM 正常密码登录、2560×1440 桌面与 PowerVR glamor 通过。六个核心桌面包文件完整性正常，系统/用户服务无失败项。公开源镜像未写入这些私人配置。

本次六个发行镜像均完成全盘 SHA256、压缩解压回读和实际只读挂载审计，覆盖 config 分区、根文件系统与 initramfs 的早期及主 CPIO。清理重置机器身份、SSH 主机密钥、pacman 本机信任状态、个人文件、网络 seed 和启动完成标记，并在首启建立新的身份和 keyring。卫生审计与硬件启动是两项不同检查，上表明确区分各自范围。操作步骤见 [README](README.md)，清理规则见 [RELEASE-HYGIENE.zh-CN.md](RELEASE-HYGIENE.zh-CN.md)。

KDE 的 UFS 系统完成首启扩容、私人 Wi-Fi seed 自动导入与删除、新 SSH 身份及 pacman 本机密钥生成、签名包下载、正常密码登录、注销重登和 Konsole/Dolphin/Kickoff 验证。持久化的 SDDM/Plasma Vulkan 配置在同一系统验证，Qt 明确选中 PowerVR BXM-4-64，并建立实际呈现用的 swapchain。本次 KDE 使用插卡状态下临时从 UFS 加载内核和根分区；拔 SD 冷启动的独立验证来自前述同 T5 启动载荷的 XFCE 测试。最终 KDE 两镜像包含实机验证后的界面配置并完成独立镜像审计，未将两个最终文件分别刷入实机。

白名单公开源码另在全新 CLI 工作目录完成十个构建阶段，生成两种介质镜像并完成解压哈希回读；源码测试 70 项、包测试 11 项、GPU 测试 15 项均通过。

CLI 的本次 SD 发行镜像经私人 Wi-Fi 配置工具派生后完整写入并回读，实机从对应 UUID 启动。首次自动联网、扩展根分区、新建 SSH 身份和 pacman 密钥、seed 导入后删除均通过；没有安装 Xorg、XFCE 或 Plasma，默认 `multi-user.target`，无失败 systemd unit。完整 `pacman -Syu` 成功，仓库当时没有待升级包；EGL/GLES 硬件像素绘制与 Vulkan 设备枚举通过。

## 图形与更新范围

已证实 T5 私有驱动可完成 EGL/GLES 绘制及像素回读，Arch Xorg 使用 PowerVR glamor。Vulkan 除设备枚举外，已验证 Qt 动画窗口、SDDM 和 Plasma 的实际界面呈现；这不代表所有 Vulkan 应用或计算负载通过。GLX/AIGLX 客户端仍是软件路径。没有据此宣称 Wayland、视频编解码或所有 OpenGL 应用已硬件加速。

KDE 默认 Plasma X11 / SDDM，两者的 Qt Quick 界面采用 PowerVR Vulkan；不替换 Arch Qt、Mesa、GLVND，也不使用实验中的 GLES 预加载适配库。KWin EGL/GLES 创建窗口 surface 时复现 PVR 调用链崩溃，合成暂时关闭。保留 Plasma 软件配置和 SDDM llvmpipe 配置作为回退；Xorg 的 PowerVR glamor 独立启用。已知鼠标指针可能显示黑色方底。启动自 Plasma 的应用可能继承 QSG/Vulkan 选择，不能把服务局部设置理解为所有子应用环境完全隔离。详细配置和回退见 [KDE.zh-CN.md](KDE.zh-CN.md)。升级前应阅读 [ROLLING-UPGRADE.zh-CN.md](ROLLING-UPGRADE.zh-CN.md)，Arch 滚动用户态、T5 内核和私有 GPU 库不能假设永远兼容。

T5 内核未启用 Landlock，pacman 保留下载用户及系统调用过滤，仅关闭不支持的文件系统沙箱。更新本机内核或上游行为后需要重新核验这一配置。

## 存储与首次启动

沿用官方 T5 GPT 的 config / efi / rootfs 顺序与启动保留区。SD 和 UFS 的配置分区偏移、逻辑扇区尺寸不同；不能通过改名或改变 `dd bs=` 转换镜像。首次扩容保持根分区起点与 UUID，修复备份 GPT 后扩展 ext4。

实测限制：无卡启动 UFS 后热插 SD 可能不识别；上电前插卡可正常工作。需要从 UFS 写 SD 时，可以保持插卡，在 U-Boot 中临时选择 UFS 启动后再核对 SD 和 CID。这是本板观察，原因尚未定位，发行 DTB 未因此加入未经验证的 GPIO/供电改动。

公开镜像不携带个人 Wi-Fi、SSH 公钥或固定 SSH 主机身份。无显示器安装可用 [Wi-Fi 私人副本工具](WIFI-FIRSTBOOT.zh-CN.md)。导入后的 seed 删除不等于闪存物理擦除，也不移除最初私人镜像中的凭据。

## 来源、许可与资产

项目自身源码采用 [MIT](LICENSE)。内核、U-Boot、固件、Arch 软件包与 GPU 用户态分别受其上游许可约束。上游 URL、版本与归档哈希在 [sources.lock.json](config/sources.lock.json)；第三方许可资料和目前仍缺少的再分发授权证据在 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)。公开发布或拥有可下载的上游文件，并不等于所有第三方组件的再分发条件已经核定。

每组发行资产应同时提供镜像的 SHA256、包版本快照、构建来源和清理审计。私人副本、旧系统备份、个人配置、开发机日志和历史候选不属于公开资产。源码白名单导出独立于镜像发布，防止把开发工作区中的这些内容一起提交。
