# A7Z T5 可选视频硬解包

`radxa-a7z-vpu 0.1.0-2` 给当前 Arch GStreamer 提供官方 Cedar/OMX 视频解码后端。
它是可选包，不改变 Chromium、Mesa、Xorg、桌面环境或现有发布镜像。

## 已验证和边界

在 A7Z、内核 `6.6.98-4-aw2511` 上，官方 CedarC 1.0.7 和 OMX 插件 1.18.3
可与 Arch GStreamer 1.28.7 配合。15 秒 1080p30 H.264 测试片经
`h264parse ! omxh264dec ! fakesink sync=false` 完成 450 帧，Cedar 中断增加
450 次，正常 EOS。该短测执行约 3.26 秒；它验证解码吞吐，不代表屏幕显示帧率。

实际输出是 DMABuf、YV12、1920×1088，带有 1920×1080 的 `GstVideoCropMeta`。
按裁剪元数据处理后，首帧与 FFmpeg 软件解码逐字节一致。另一份 320×180 H.264
样片的 29 帧也与软件解码完全一致。普通用户的 1920×1080 XVideo 窗口又完成
450 帧、零丢帧播放，详见 [显示验收及边界](VALIDATION.zh-CN.md)。编码、HEVC、VP9、
音频及完整播放器操作仍需分别验证。

**这不等于 Chromium 内视频硬解。** 当前 Arch Chromium 153 没有 Cedar 或
GStreamer 解码入口，也没有可用的 A733 VA-API 驱动。Chromium 的 PowerVR
ANGLE/Vulkan 网页合成、WebGL 加速和这里的 VPU 视频解码是两条独立路径。
Chromium 的硬解需要厂商 `VmxGstVideoDecoder` 补丁移植到新版本，或实现适配当前
Cedar 内核的 VA-API/V4L2 桥接。仅设置浏览器 flags 或安装本包不能补齐接口。
官方 T5 的 Chromium 120 使用 GStreamer/OMX 定制后端；本包不包含它。

## 构建与使用

在 Linux/WSL 中，从锁定 T5、保留 dpkg 元数据的官方 rootfs 构建：

```sh
python3 tools/package_vpu.py --vendor-root /path/to/vendor/t5 --output /path/to/new-vpu-output
```

依赖主机 `readelf`、`patchelf`、`zstd`。输出目录必须不存在或为空，避免覆盖旧包。
安装依赖需完整滚动升级，随后安装本地包：

```sh
sudo pacman -Syu --needed gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad
sudo pacman -U radxa-a7z-vpu-0.1.0-2-aarch64.pkg.tar.zst
sudo udevadm control --reload
sudo udevadm trigger --action=change --subsystem-match=cedar_ve
sudo udevadm trigger --action=change --subsystem-match=cedar_ve2
sudo udevadm trigger --action=change --subsystem-match=dma_heap --sysname-match=system
a7z-vpu-run gst-inspect-1.0 omxh264dec
a7z-vpu-run gst-launch-1.0 filesrc location=/absolute/path/test.mp4 \
  ! qtdemux ! h264parse ! omxh264dec ! fakesink sync=false
```

使用当前本地桌面会话用户运行。udev/logind 按会话授予 `cedar_dev`、
`cedar_dev_ve2` 和 `dma_heap/system` 的访问 ACL，不把设备设成所有人可写。
纯 SSH 会话不保证获得设备 ACL；不要以 `chmod 666` 代替会话授权。

库和 OMX 插件放在 `/usr/lib/radxa-a7z-vpu/`，配置放在
`/usr/share/radxa-a7z-vpu/`。只有 `a7z-vpu-run` 的子进程选择它们，普通应用
不扫描此插件目录。GStreamer 缓存放在当前用户的 `~/.cache/a7z-vpu/`。
该 wrapper 不应写入全局环境或 source 到桌面会话中。

上游库会尝试读取可选 `/etc/cedarc.conf`；本包保留私有配置样本但不写这个系统路径，
验证采用库的默认值，因此可能看到缺少该可选配置的日志。

## 来源

- [Radxa 视频编解码文档](https://docs.radxa.com/en/cubie/a7z/app-dev/video-codec)
- [官方设备会话权限规则](https://github.com/radxa-pkg/allwinner-prebuilt/blob/main/debian/libgstreamer-openmax-allwinner.sunxi-ve.udev)
- [Chromium 153 视频后端构建配置](https://github.com/chromium/chromium/blob/153.0.8010.36/media/gpu/BUILD.gn)
- [Chromium VA-API 验证方法](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/docs/gpu/vaapi.md)

完整上游记录见包内 `UPSTREAM-NOTICE.txt` 和 `vpu-provenance.json`。
