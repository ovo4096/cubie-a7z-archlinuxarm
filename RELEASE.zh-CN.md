# cubie-a7z-archlinuxarm 发行说明

本项目为 Radxa Cubie A7Z 提供基于官方 T5 / Trixie BSP 的 Arch Linux ARM。发布渠道为 [GitHub Releases](https://github.com/ovo4096/cubie-a7z-archlinuxarm/releases)，具体下载项、文件哈希与验证状态以各 release 为准。

| 变体 | SD / 512 字节 | UFS / 4096 字节 |
|---|---|---|
| CLI | 构建与验证中 | 构建与验证中 |
| XFCE + LightDM | 已实机验证 | 已实机验证 |
| KDE Plasma X11 + SDDM | 构建与验证中 | 构建与验证中 |

XFCE 的 SD 与 UFS 均已验证 T5 `6.6.98-4-aw2511` 启动、实际根分区、Wi-Fi/SSH、首次扩容、LightDM 正常登录和完整 2560×1440 桌面。UFS 完成过拔 SD 冷启动；SD 与 UFS 镜像使用不同 UUID。该结论来自先前同 BSP 的实机验证，不自动覆盖未来所有镜像版本、外设或长期负载。

最新清理流程会重置机器身份、SSH 主机密钥、pacman 本机信任状态、个人文件、网络 seed 和启动完成标记，并在首启建立新的身份和 keyring。**每个新发行文件仍须分别经过自身的清理审计和适用的启动检查**；不能把构建成功等同于已验收。操作步骤见 [README](README.md)，清理规则见 [RELEASE-HYGIENE.zh-CN.md](RELEASE-HYGIENE.zh-CN.md)。

## 图形与更新范围

已证实 T5 私有驱动可完成 EGL/GLES 绘制及像素回读，Arch Xorg 使用 PowerVR glamor。Vulkan 目前仅验证设备枚举，GLX/AIGLX 客户端仍是软件路径。没有据此宣称 Wayland、Vulkan 渲染/计算、视频编解码或所有 OpenGL 应用已硬件加速。

KDE 默认 Plasma X11 / SDDM，Qt Quick 软件后端、KWin X11 合成关闭；它与 Xorg 的 glamor 是不同层次。KDE 的 X11 上游支持有时间边界，见 [KDE.zh-CN.md](KDE.zh-CN.md)。升级前应阅读 [ROLLING-UPGRADE.zh-CN.md](ROLLING-UPGRADE.zh-CN.md)，Arch 滚动用户态、T5 内核和私有 GPU 库不能假设永远兼容。

T5 内核未启用 Landlock，pacman 保留下载用户及系统调用过滤，仅关闭不支持的文件系统沙箱。更新本机内核或上游行为后需要重新核验这一配置。

## 存储与首次启动

沿用官方 T5 GPT 的 config / efi / rootfs 顺序与启动保留区。SD 和 UFS 的配置分区偏移、逻辑扇区尺寸不同；不能通过改名或改变 `dd bs=` 转换镜像。首次扩容保持根分区起点与 UUID，修复备份 GPT 后扩展 ext4。

实测限制：无卡启动 UFS 后热插 SD 可能不识别；上电前插卡可正常工作。需要从 UFS 写 SD 时，可以保持插卡，在 U-Boot 中临时选择 UFS 启动后再核对 SD 和 CID。这是本板观察，原因尚未定位，发行 DTB 未因此加入未经验证的 GPIO/供电改动。

公开镜像不携带个人 Wi-Fi、SSH 公钥或固定 SSH 主机身份。无显示器安装可用 [Wi-Fi 私人副本工具](WIFI-FIRSTBOOT.zh-CN.md)。导入后的 seed 删除不等于闪存物理擦除，也不移除最初私人镜像中的凭据。

## 来源、许可与资产

项目自身源码采用 [MIT](LICENSE)。内核、U-Boot、固件、Arch 软件包与 GPU 用户态分别受其上游许可约束。上游 URL、版本与归档哈希在 [sources.lock.json](config/sources.lock.json)；第三方许可资料和目前仍缺少的再分发授权证据在 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)。公开发布或拥有可下载的上游文件，并不等于所有第三方组件的再分发条件已经核定。

每组发行资产应同时提供镜像的 SHA256、包版本快照、构建来源和清理审计。私人副本、旧系统备份、个人配置、开发机日志和历史候选不属于公开资产。源码白名单导出独立于镜像发布，防止把开发工作区中的这些内容一起提交。
