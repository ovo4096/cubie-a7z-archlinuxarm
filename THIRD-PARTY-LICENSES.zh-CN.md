# 第三方组件许可与源码定位

核查日期：2026-09-14。本项目公开源码、构建工具，并按项目发布者决定提供包含官方 BSP 的镜像。下述第三方二进制仍存在未核定的授权和对应源码材料缺口；提供镜像这一发布决定不等于相关权利人已经授权。下载脚本同时保留官方来源和校验值，便于在本地构建和核对。

此表记录实际发现的材料及缺口；不把打包仓库的总许可证自动套到嵌入的第三方二进制。尤其是 GPL 打包模板，不能替代具体二进制的许可与对应源码。

## PVR 图形栈

| 组件 | 已确认事实 | 尚待补齐 |
| --- | --- | --- |
| `pvrsrvkm.ko` 内核模块 | `rogue_km/README` 明确该内核 DDK 可按 MIT 或 GPLv2 分发；源码含 `MIT-COPYING`、`GPL-COPYING`，核心文件也有双许可声明 | 按实际选用条款保留通知，保存精确源码、补丁、DKMS 配置与内核构建环境 |
| PVR 用户态 `24.2.6603887` | T5 的 `xserver-xorg-img-bxm_1.21.1-2_arm64.deb` 是预编译容器；其实际 dpkg 包名为 `xserver-xorg-img-bxm-1.21.1-2.deb`、版本 `1.0.1`。包内未发现 copyright/EULA；固定上游仓库树也未发现匹配的许可文档 | 对这些具体 Imagination ELF 库的明确再分发许可，及任何相应条件；当前不能按 GPL-3+ 包装声明宣称已核准 |
| `rgx.fw.36.56.104.183` 与 `rgx.sh.36.56.104.183` | 来自同一 T5 预编译包，由本项目 BSP firmware 包收录 | 对这两个具体固件的许可。别处的 `LICENSE.powervr` 或 SDK 协议不能在未确认适用文件和版本时直接移用 |

PVR 内核模块来源链固定为：

- [aw-drivers-dkms `0.1.0-3`](https://github.com/radxa-pkg/aw-drivers-dkms/tree/2b09af1ed0c59b0fdc0650de71bef636551b6641)，commit `2b09af1ed0c59b0fdc0650de71bef636551b6641`。
- 其 `src` 子模块为 [allwinner-bsp `37a10166bbdbc8a8f1481b65c91494212e2af909`](https://github.com/radxa/allwinner-bsp/tree/37a10166bbdbc8a8f1481b65c91494212e2af909/modules/gpu/img-bxm/linux/rogue_km)。这是外置 DKMS 模块的源基线，不能误用内核主 BSP 的另一个 commit。
- [许可证说明](https://github.com/radxa/allwinner-bsp/blob/37a10166bbdbc8a8f1481b65c91494212e2af909/modules/gpu/img-bxm/linux/rogue_km/README)、`MIT-COPYING`、`GPL-COPYING`、`INSTALL`、`build/linux`、打包仓库的 `debian/img-bxm-dkms.dkms`、`debian/rules` 和补丁都应随源码材料保留。

PVR 用户态预编译来源链为 [allwinner-prebuilt `1.4.10-2`](https://github.com/radxa-pkg/allwinner-prebuilt/tree/ad1879c83091ca03d303f7d7474d472de41baac9)，commit `ad1879c83091ca03d303f7d7474d472de41baac9`；子模块是 [allwinner-debian `43fe44a304e8c06c6275769c4731ff82265325a7`](https://github.com/radxa/allwinner-debian/tree/43fe44a304e8c06c6275769c4731ff82265325a7)，文件位于 `packages/arm64/xserver/`。其 `.github/local/Makefile.local` 直接复制预编译 `.deb`，不是这些 PVR 用户态库的源代码构建流程。

## AIC Wi-Fi / Bluetooth 与固件

驱动的精确打包源码是 [aic8800 `5.0+git20260123.5f7be68d-7`](https://github.com/radxa-pkg/aic8800/tree/6e076049b719ac2ff7ce5c92786a680407b11cdb)，commit `6e076049b719ac2ff7ce5c92786a680407b11cdb`。USB 驱动位于 `src/USB/driver_fw/drivers/aic8800`；相应 DKMS 配置、`debian/rules`、`.github/local/Makefile.local` 和 `debian/patches` 必须一并保留。

Radxa 维护者在 [issue #54](https://github.com/radxa-pkg/aic8800/issues/54) 解释顶层 GPLv3 来自通用打包模板，并于 2025-09-17 表示已向 AIC 确认当前驱动源码是 GPLv2。当前 `debian/copyright` 也区分了 `src/*` 的 GPL-2 和包装代码的 GPL-3+。这支持驱动源码的许可定位，不能据此推断所有 AIC 固件已按同样条款获准再分发。

T5 `aic8800-firmware` 包和固定源码树带有固件二进制，但本轮没有找到明确适用于本项目 USB 固件集合的厂商再分发许可或固件的对应源代码。2026-07-21 的 [AIC SDIO 驱动 RFC 原始邮件镜像](https://lwn.net/Articles/1083998/) 还把固件再分发许可未具备列为已知限制。该 RFC 讨论 SDIO，上述说明只作为许可仍须单独确认的旁证，不能当作 T5 USB 固件被明确禁止分发的条款。

`radxa-firmware 0.2.39` 对应 [commit `7406fb7ff37e5436c6072da7b1b3965aa579d0a8`](https://github.com/radxa-pkg/radxa-firmware/tree/7406fb7ff37e5436c6072da7b1b3965aa579d0a8)。它在本项目中只用于锁定官方基线，包中其他板卡的 Broadcom/Cypress/Realtek/Mali 等载荷未被选入本项目 BSP firmware 包；本项目 firmware 的实际来源是上述 AIC/PVR 子包，不能靠 `radxa-firmware` 的总许可证替代它们的许可核定。

## Linux、设备树与 U-Boot 的固定源码链

以下是 T5 已定位的源码和构建配方，不是指向会变化的 latest 分支：

| 部分 | 固定源码 |
| --- | --- |
| 内核 Debian 打包与补丁 `6.6.98-4` | [linux-aw2511 `8c5a51bc80717b33cb2a1c66705f67592b772c92`](https://github.com/radxa-pkg/linux-aw2511/tree/8c5a51bc80717b33cb2a1c66705f67592b772c92) |
| Linux 内核树 | [radxa/kernel `61f3fe291c7a0ca97a038194bb242b133971b76e`](https://github.com/radxa/kernel/tree/61f3fe291c7a0ca97a038194bb242b133971b76e) |
| 内核 BSP 驱动树 | [allwinner-bsp `f51e1e6195d4350abc590bff852e213279e660a6`](https://github.com/radxa/allwinner-bsp/tree/f51e1e6195d4350abc590bff852e213279e660a6) |
| A7Z DTS/板级配置 | [allwinner-device `ca4d6c33e4862cf976037ee6305712eb7b3a92b8`](https://github.com/radxa/allwinner-device/tree/ca4d6c33e4862cf976037ee6305712eb7b3a92b8) |
| U-Boot 打包、patches、setup、构建配方 | [u-boot-dlan17 `039e1540b8e3fc92242da7a391e3de3eed1d3bb2`](https://github.com/radxa-pkg/u-boot-dlan17/tree/039e1540b8e3fc92242da7a391e3de3eed1d3bb2) |
| U-Boot 源树 | [dlan17/u-boot `24da4dae76374353cbe381e3074f2794dacafc0c`](https://github.com/dlan17/u-boot/tree/24da4dae76374353cbe381e3074f2794dacafc0c) |
| ARISC 源子模块 | [allwinner-arisc `0d2886ca5ed28e7008bbea965148fae144f99c6e`](https://github.com/radxa/allwinner-arisc/tree/0d2886ca5ed28e7008bbea965148fae144f99c6e) |
| DRAM 支持子模块 | [allwinner-dramlib `b1c31a940733da15a127be74dc9cb90bdd01a516`](https://github.com/radxa/allwinner-dramlib/tree/b1c31a940733da15a127be74dc9cb90bdd01a516) |
| 打包仓库 ATF 子模块（不能代替 A7Z 预编译 BL31 的证明） | [dlan17/trusted-firmware-a `f4c0b0dba78a2d9916154c130979992caa3f3156`](https://github.com/dlan17/trusted-firmware-a/tree/f4c0b0dba78a2d9916154c130979992caa3f3156) |
| 打包工具子模块 | [tina5.0_aiot/lichee/tools `2c5370f4574f2cf67512cf16000d55947cc9b82c`](https://gitlab.com/tina5.0_aiot/lichee/tools/-/tree/2c5370f4574f2cf67512cf16000d55947cc9b82c) |

本项目的 `tools/package_bsp.py` 重新封装 T5 已构建的内核和 U-Boot，不声称已经从上述源码复现每个二进制。对将来的 GPL 二进制发布，应保存匹配版本完整源树、子模块、补丁、配置（包括镜像中的 `/boot/config-6.6.98-4-aw2511`）、构建/安装脚本和必要接口定义，并明确提供接收者可取得的对应源码；只给一个总仓库或 latest 链接不足以建立这些具体二进制的来源对应关系。

另外，A7S/A7Z 的 U-Boot 配方会嵌入 `awbin/a733/bl31.bin`、`awbin/a733/ddr.bin` 及生成的 SCP。开源 U-Boot 主程序的许可证不能自动覆盖这些嵌入成分。其具体许可证及源码/二进制分发条件仍须逐项确认，因此不能把“已定位 U-Boot 主程序源码”写成“整个启动载荷再分发已全部核准”。

上述固定打包 commit 中两个预编译输入的 SHA256 为：

- `awbin/a733/bl31.bin`，115677 字节：`b009aad73508d53ee3313ba61e4a2a3a7c510506ad39968d635c05a81910e002`。
- `awbin/a733/ddr.bin`，232409 字节：`d89804f404f2eef6ef5b03d82a310ef0906c4db8ded760be221b131f5c813a05`。

SCP 由固定 ARISC/DRAM 子模块通过 [`.github/local/Makefile.local`](https://github.com/radxa-pkg/u-boot-dlan17/blob/039e1540b8e3fc92242da7a391e3de3eed1d3bb2/.github/local/Makefile.local) 中 `%/scp.bin` 规则生成，A733 平台选择 `sun60iw2p1_defconfig`。配方下载的 ARISC 工具链来自 `radxa/allwinner-toolchain` 的 `aiot-linux-v1.4.6` release。以上仅定位构建输入，尚未声称逐组件重编译后与 T5 最终启动二进制一致。

## 其他包与本项目文件

Arch Linux ARM、Xorg、KDE、XFCE、Mesa、OpenSSL 等维持各自的许可证。包名、版本、缓存哈希和本地 `/usr/share/licenses` 有助于审计，但不替代未来二进制发布所需的各包许可通知及适用的对应源码材料。PVR 私有目录中的 OpenSSL 1.1 兼容库单独保留其 Debian copyright；它不解决 PVR 库本身的许可问题。

本项目自行编写的构建、清理和首次启动代码按仓库自身许可证发布。源码导出不携带官方 rootfs、预编译 `.deb`、固件、私有 GPU 库、旧镜像、板卡备份或诊断记录；独立镜像附件包含的 BSP/PVR 二进制仍受上文各项事实和缺口约束。后续若取得授权，应在公开许可证材料中记录授权方、适用的具体文件/版本和条件，并更新相应发布说明。
