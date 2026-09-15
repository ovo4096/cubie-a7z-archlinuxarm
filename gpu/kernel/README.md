# PowerVR 内核模块的 fdinfo 修复

T5 的 `pvrsrvkm` 采用按连接初始化的模式：打开 DRM 设备时，`drm_file->driver_priv` 可以合法地为空，直到私有初始化 ioctl 完成。原 `pvr_show_fdinfo` 没有覆盖这个状态，查询 `/proc/PID/fdinfo/FD` 时可能解引用空指针，导致整机 kernel panic。该问题在 KDE 重启过程中被 `systemd-coredump` 的文件描述符信息采集触发；它也可能被其他读取 fdinfo 的程序触发，不能靠关闭崩溃文件存储完整解决。

[补丁](0001-use-generic-drm-fdinfo.patch)使该回调只调用 Linux 的 `drm_show_fdinfo`，保留标准 DRM 信息，停止读取 PowerVR 私有连接统计。T5 的 `drm_driver.show_fdinfo` 未注册其他回调，因此这个调用不会递归回到 PowerVR 包装函数。修改不改变渲染 ioctl、固件或用户态接口；代价是不再通过 fdinfo 提供原有 PVR 专用诊断字段。它不代表审计或修复了驱动中所有其他生命周期与 ioctl 问题。

## 构建与来源

[构建工具](../../tools/build_gpu_kmod.py)由 BSP 打包流程调用，使用锁定官方 T5 rootfs 的 `img-bxm-dkms` 源码、`6.6.98-4-aw2511` 头文件、配置和 `Module.symvers`。源码和头文件复制到构建机的独立临时目录后才应用补丁；头文件附带的 ARM 主机构建工具不能直接在 x86_64 上运行，需要重新生成本机工具。构建失败、模块架构或 ABI 标识不匹配时停止打包，不回退到有缺陷的旧模块。

修复由 `radxa-a7z-gpu-kmod 0.1.0_3-3` 提供，对应的 GPU 用户态包修订为 `24.2.6603887_t5-7`，依赖这一模块修订；私有用户态二进制保持 T5 版本。安装位置仍由 BSP 包统一管理，并由原启动更新流程执行 `depmod`。模块使用 T5 内核构建规则要求的 XZ CRC32 校验和 1 MiB 字典；CRC64 格式会被该内核的模块解压器拒绝。

构建记录包含补丁、输入和输出模块的 SHA256、匹配的头文件与源码、工具链版本。`vermagic` 必须精确匹配原模块。T5 未启用 `CONFIG_MODVERSIONS`，因此不能把 `Module.symvers` 中的符号检查描述为已验证内核符号 CRC。相同版本标识和静态检查不能代替板上的实际模块加载与图形测试。

## 验证边界

回归检查应在安装修复包并重新启动后进行，覆盖未执行初始化 ioctl 的新 DRM 文件描述符信息读取、现有图形进程的 fdinfo 采集，以及正常 GPU 绘制和桌面退出/重启。旧模块会因该查询动作崩溃，不能在旧系统上直接运行回归动作。

本次编译和实机验收结果以 [发行说明](../../RELEASE.zh-CN.md)及发布资产中的硬件摘要为准。专有 fdinfo 统计被省略不等于 GPU 被禁用；是否使用 GPU 应结合实际渲染器、像素绘制和应用表现验证。
