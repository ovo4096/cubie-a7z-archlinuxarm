# 公开镜像的身份与凭据清理

本文件描述本项目源码、构建工具和镜像的发布卫生检查。第三方 BSP 二进制的授权缺口见 [THIRD-PARTY-LICENSES.zh-CN.md](THIRD-PARTY-LICENSES.zh-CN.md)；身份清理和技术检查通过不代表第三方二进制已经取得再分发授权。

公开基础镜像必须不含 Wi-Fi 凭据、SSH 私钥、构建机的 pacman 私钥及设备身份。用户预设 Wi-Fi 应由 `tools/personalize.py` 写入独立私人镜像；私人镜像文件名、元数据和 config 分区保留明确标记，不能作为公版附件上传。

## 构建集成

在所有 pacman 安装、桌面配置和 `rootfs.py finalize` 完成后，卸载 chroot 的 `/dev`、`/proc`、`/sys` 和缓存绑定挂载，再运行：

```sh
# 默认只读；发现待清理项时退出码为 2。
python3 tools/sanitize.py --rootfs /work/rootfs --report /work/rootfs-audit-before.json

# 仅允许 Linux root，对离线的构建目录清理。
python3 tools/sanitize.py --rootfs /work/rootfs --apply --report /work/rootfs-audit-after.json
```

`sanitize_root(root, apply=False)` 可供构建器调用，默认干运行；`audit_root(root)` 只返回报告。报告只包含固定分类、计数和检查结果，不写出配置内容、SSID、密码、密码哈希、任意用户文件名或私钥指纹。退出码 0 表示检查范围内干净，2 表示仍有待处理项，1 表示安全检查或必需条件失败。不要忽略非零退出码。

操作前必须安装 `a7z-keyring-init`、配套 systemd service 和 `archlinuxarm-keyring`。清理器会创建该服务的 `multi-user.target.wants` 链接；`tools/package_base.py` 会收录两个 `runtime/a7z-keyring-init*` 源文件。无需在清理后再次执行 pacman 或 chroot 初始化命令，否则会重新产生构建身份。

公开构建只允许 `root` 和 `alarm` 两个预期管理账户（普通系统服务账户保留）。`root` 必须锁定，`alarm` 必须使用文档公开的初始密码 `alarm`。清理器通过构建宿主的 libcrypt 验证这一点，但不修改、打印或导出 `/etc/shadow`。自定义密码请作为用户设备个性化处理，不要把个人常用密码设置进公版。

## 清理范围

| 内容 | 处理方式 |
| --- | --- |
| NetworkManager profile、状态、Wi-Fi/VPN 配置 | 清空连接目录与运行状态，包括 iwd、wpa_supplicant、ConnMan、WireGuard/OpenVPN 的本机配置 |
| SSH 主机密钥、用户 `.ssh` / `.gnupg` / history | 删除主机密钥；`/root` 和 `/home/alarm` 从 `/etc/skel` 重建 |
| home 中由包拥有的文件 | 有 skel 默认文件时恢复默认；没有可恢复默认的包文件时停止，要求人工复核，不静默删除 |
| `/etc/machine-id`、D-Bus machine-id | machine-id 清空；D-Bus 路径统一指向 `/etc/machine-id` |
| random seed、systemd credential secret、hostid | 删除；设备启动后自行建立 |
| pacman 本地签名私钥与信任库 | 清空整个 `/etc/pacman.d/gnupg`；保留 `/usr/share/pacman/keyrings` 中随软件包安装的公钥 |
| DHCP 租约、Bluetooth 配对、桌面登录状态 | 清空相应本机状态目录 |
| `/var/lib/a7z` | 清空首次启动完成标记、keyring 标记、GPT 备份、启动快照等本机任务状态 |
| 日志、缓存、tmp、run、构建残留 | 删除内容；保留 pacman 已安装软件数据库和公共软件版本快照 |
| `/config` | 公版源 rootfs 清空；镜像构建器随后生成公共说明模板和镜像 manifest |

额外扫描 `/etc`、`/opt`、`/srv`、`/usr/local` 中不超过 1 MiB 的普通文件，发现错放的 PEM/SSH 私钥头时阻止 clean 结果；不会擅自删除用途未知的程序文件。这是针对已知身份位置的发布检查，不能替代对新增自定义文件及大文件的内容复核。

清理器拒绝根目录、系统目录、挂载中的 rootfs、嵌套绑定挂载及受管路径中的父级软链接。叶子软链接只被解除，不遍历目标。应独占离线构建目录使用该工具，不要同时启动会写入该目录的服务或构建进程。

## 首次启动与滚动升级

`a7z-keyring-init.service` 在 NetworkManager、sshd、首次启动 seed 导入和图形登录之前运行：

1. `pacman-key --init` 创建该设备自己的本地签名密钥。
2. `pacman-key --populate` 导入并信任本地安装的所有发行公钥集合，包括 `archlinuxarm`，以及将来明确安装的项目仓库 keyring 包。
3. 两步都成功后才写入完成标记；失败不标记完成，可以修复后重试服务。

此过程不用 keyserver、不下载密钥，不把构建私钥发给每台设备，也不关闭 pacman 的包签名验证。之后正常使用 `sudo pacman -Syu` 更新 Arch Linux ARM 软件；BSP 内核、内核模块和 PVR 用户态版本兼容关系仍由包依赖和项目维护策略约束。

`a7z-firstboot` 另行生成 SSH 主机密钥并导入 `/config` 的可选私人 seed。确认成功导入后删除实际 Wi-Fi、authorized keys、hostname seed；私人镜像声明仍保留。首次启动完成标记必须在公版中缺席，保证导入路径会运行。

## 审核实际镜像字节

必须从已清理的 rootfs 创建新的镜像文件。不要只删除旧镜像中的文件再公开：被删除凭据仍可能存在于文件系统空闲块中。

对生成后的 root 分区，使用 `losetup --read-only --sector-size 512`（SD）或 `4096`（UFS）连接镜像，再以 `mount -o ro,noload` 挂载 ext4。之后执行：

```sh
python3 tools/sanitize.py --rootfs /work/image-root --readonly-image-audit \
  --report /work/image-root-audit.json
```

`--readonly-image-audit` 不能与 `--apply` 同用。工具从 `/proc/self/mountinfo` 确认根目录确实是 `/dev/loopN[pN]` 上只读挂载的 ext4，且没有任何嵌套挂载。普通 `sanitize_root()` 永远不接受这个例外。读完解除挂载并释放 loop。

config 分区必须单独只读检查：不含 `wifi/*.nmconnection`、`ssh-authorized-keys`、`hostname`、`a7z-private-seed.json`、`PRIVATE-IMAGE.txt`；镜像元数据必须声明 `private_seed_included=false`。可以保留公共 README、examples 和 `a7z-image.json`。只有检查 root 分区而未检查 FAT config 分区，不足以断言整个镜像没有预置凭据。

## 公开附件与源码导出

公开导出应从全新目录按白名单复制项目源码、测试、构建说明和必要许可证；不要对工作区或旧 `out/` 执行整体复制。禁止自动复制 `backups/`、`diagnostics/`、构建日志、真实板卡审计、旧候选镜像、SSH known_hosts、终端记录和屏幕截图。

```sh
python3 tools/sanitize.py --output-dir /work/public-export \
  --report /work/public-export-audit.json
```

输出目录审计会发现私人 evidence 路径、私人 seed 标记、声明含 seed 的 JSON 及明文私钥头；`.img`、`.img.zst`、`.pkg.tar.zst` 按不透明文件统计，不伪称已经检查其内部。源码中的示例、测试夹具可能故意包含假凭据标记，应作为代码人工复核；这个输出目录检查主要用于发行附件目录。

## 本轮验证

`tests/test_sanitize.py` 覆盖干运行不改动和报告脱敏、身份清理后幂等、包文件保护、软链接和挂载边界、默认密码策略、遗漏私钥仍阻止放行、首次 keyring 初始化失败不写标记，以及只读 loop 审核与可写清理的隔离。另在完整 AArch64 rootfs 的一次性副本执行两轮真实 keyring 初始化，确认两轮生成不同的设备本地密钥，每轮重复运行保持幂等，再次清理后检查通过。实体板和已有镜像未由清理验证修改。
