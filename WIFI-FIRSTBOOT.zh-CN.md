# 烧录前配置 Wi-Fi：无显示器首次启动

CLI、XFCE 和 KDE 镜像使用同一套首次启动逻辑。先从公开原始 `.img` 创建带 Wi-Fi 的**私人副本**，再把私人副本按原来的 SD/UFS 流程烧录。公开下载文件不会被修改。

在源码仓库目录运行 [tools/personalize.py](tools/personalize.py)。它只读写普通镜像文件，校验源 SHA256、主/备 GPT、512/4096 扇区布局和 config FAT 边界；不会选择、挂载或写入任何实体磁盘。只有私人副本的 config 分区被修改，启动载荷、EFI、根文件系统和 UUID 保持原样。

## Windows：隐藏输入密码

需要 Python 3、WSL Ubuntu，以及 WSL 中的 mtools。先安装依赖：

```powershell
wsl -d Ubuntu -- sudo apt-get install -y mtools
```

将下载的 `.img.zst` 解压为 `.img`，保留与原始 `.img` 配套的 `.img.sha256` 在同一目录。源文件和清单中的文件名必须相同。然后在 PowerShell 运行：

```powershell
py -3 tools/personalize.py `
  --image .\downloads\cubie-a7z-archlinuxarm-xfce-t5-sd-512.img `
  --output .\private\cubie-a7z-archlinuxarm-xfce-t5-sd-512-private.img `
  --ssid "你的 Wi-Fi 名称"
```

请预先建立 `private` 目录。程序会提示输入 Wi-Fi 密码，输入不会显示，也不会作为命令行参数或环境变量传给 WSL。请勿把密码直接写入 shell 命令。输出文件名必须包含 `-private`，输出文件及其校验清单不能已存在。

Windows 路径会自动转成 WSL 路径，默认使用 `Ubuntu`；其他发行版使用 `--wsl-distribution 名称`。Windows 中的私人文件仍受 Windows 文件夹 ACL 管理，请放在仅自己可访问的目录。

UFS 使用对应的 `ufs-4096.img` 作为源，输出另一个 `ufs-4096-private.img`；CLI 和 KDE 版同理。不能用 SD 镜像生成 UFS 版，也不能把已启动系统的磁盘备份当作 pristine 公开源。应从校验过的原始发布镜像开始。

## Linux / WSL

Linux 直接运行同一工具，无需 root：

```sh
python3 tools/personalize.py \
  --image downloads/cubie-a7z-archlinuxarm-xfce-t5-sd-512.img \
  --output private/cubie-a7z-archlinuxarm-xfce-t5-sd-512-private.img \
  --ssid '你的 Wi-Fi 名称'
```

也可以用 `--password-file /受限路径/wifi-password` 从单行文件读取。该文件必须位于 Linux/WSL 原生文件系统，由运行用户或 root 拥有，权限为 `0600` 或更严格；符号链接、可被组/其他用户读取的文件会被拒绝。Windows 挂载盘通常不能通过这一权限检查，推荐使用隐藏输入。密码文件内容不要出现在终端、日志或版本库中，用完后自行保管或删除。

若没有配套 `.img.sha256`，可以用 `--sha256` 提供已从可信发布清单核对的原始镜像哈希；不要为了绕过校验而临时相信未知文件自身计算出的哈希。

## 可选项目与网络范围

- `--hidden`：用于不广播 SSID 的网络。
- `--ssh-key 路径`：导入 OpenSSH 公钥到 alarm 的 `authorized_keys`，可提供多行公钥；不能提供私钥。
- `--hostname a7z-home`：设置一个由小写字母、数字、短横线组成的单段主机名，最长 63 字符。

当前向导配置 WPA2-Personal，也适用于允许 WPA2 连接的 WPA2/WPA3 混合网络。密码须为 8–63 个可打印 ASCII 字符，或已有的 64 位十六进制 PSK。纯 WPA3-SAE、企业 802.1X、开放网络和静态 IP 不在此向导范围内。SSID 支持 UTF-8，编码后最多 32 字节；IPv4 使用 DHCP，IPv6 自动配置。向导不会固定无线网卡接口名。

WPA2 口令会转换为与该 SSID 对应的 PSK；**PSK 本身仍是可用于接入网络的凭据**。私人镜像、临时副本、备份和烧录后的卡都应视为含有凭据，不能公开发布。输出 JSON 不记录 SSID、密码、PSK 或公钥内容。

## 烧录与首次启动

烧录生成的 `-private.img`。该文件有自己新的 `.img.sha256` 和 `.img.json`；安装器应使用这份私人镜像的校验信息。SD 和 UFS 的具体写入方式见 [README](README.md)。插卡应在上电前完成；当前板子的 SD 热插入限制见 [发行说明](RELEASE.zh-CN.md)。

首次启动时，[a7z-firstboot](runtime/a7z-firstboot) 在 NetworkManager 和 SSH 启动前导入：

| config 中的文件 | 导入位置 |
|---|---|
| `wifi/*.nmconnection` | `/etc/NetworkManager/system-connections/a7z-seed-*.nmconnection`，root 所有、`0600` |
| `ssh-authorized-keys` | `/home/alarm/.ssh/authorized_keys`，alarm 所有、`0600` |
| `hostname` | `/etc/hostname`，同时更新本次运行的主机名 |

导入文件落盘并成功生成 SSH 主机密钥后，程序删除上述已经导入的 FAT seed，再记录完成标记。它保留 `PRIVATE-IMAGE.txt` 和不含凭据的私人声明；删除 seed 不会让私人镜像自动变成可公开镜像。已有配置与 seed 冲突或 seed 格式不正确时，程序不覆盖原配置，并保留尚未清理的 seed 供检查，不会把解析输入打印到日志。

FAT 删除只取消文件引用，**不能保证闪存、文件系统空闲区或 SSD 的物理擦除**。此外，最初用于烧录的私人 `.img` 仍保留 seed；已成功连接的系统仍须在 root 文件系统保存网络凭据。该功能不提供“删除后可安全转让介质”的保证。

无需显示器：等待启动与首次扩容完成后，到路由器 DHCP 客户端列表寻找配置的主机名，再以 `alarm` 使用对应 IP 连接 SSH。首次连接应核对新的 SSH 主机身份；首次登录后更改镜像的初始账号密码。Wi-Fi 密码与 Linux 登录密码是两件事，本工具不改变 Linux 登录密码。

若连接失败，可在本地串口检查 `systemctl status a7z-firstboot NetworkManager` 和 `journalctl -b -u a7z-firstboot`。不要把含 PSK 的连接文件原样贴到公开 issue。首次导入已完成后再换网络，应通过 NetworkManager 修改连接；本工具用于创建新的首次启动私人镜像。

## 已验证范围

使用新建测试镜像验证了两种扇区的实际 FAT 注入、源镜像 SHA256 不变、config 外所有字节不变、私人标记、重复私有化拒绝和 profile 回读。首次启动导入、权限、失败重试及清理已在临时目录和两种扇区的实际 FAT loop 上验证；NetworkManager 的离线解析器接受生成的 Unicode SSID 配置。这组工具测试未写入实体开发板或公开源镜像。

随后使用私人副本完成 CLI SD、XFCE SD 与 KDE UFS 的实体首次启动验证：自动连接 Wi-Fi，导入的连接配置归 root 所有且权限为 `0600`，成功后删除 config 中的 seed，并生成新的 SSH 主机身份和 pacman 本机密钥。公开源镜像保持清洁；具体镜像及桌面验证范围见 [发行说明](RELEASE.zh-CN.md)。

实现依据：[mtools 镜像操作说明](https://www.gnu.org/software/mtools/manual/mtools.html)、[NetworkManager keyfile 格式](https://networkmanager.pages.freedesktop.org/NetworkManager/NetworkManager/nm-settings-keyfile.html)。
