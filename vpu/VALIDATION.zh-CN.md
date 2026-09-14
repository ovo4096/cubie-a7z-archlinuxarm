# VPU 安装与显示验证（2026-09-15）

本次验证对象是实际安装的可选包 `radxa-a7z-vpu 0.1.0-1`，未替换系统图形库。
包 SHA256：`ec4ee1a2d1759776403de863b3278d7cd070433f1f4f82cdb236f33d64bee8f4`。
环境为 Cubie A7Z、T5 内核 `6.6.98-4-aw2511`、Arch GStreamer 1.28.7、
官方 CedarC 1.0.7 / OMX 插件 1.18.3、XFCE/Xorg。

## 结果

| 检查 | 实测结果 |
| --- | --- |
| 包构建 | 两次完整构建字节一致；5 项安全/可复现测试通过；50 个来源及包内文件哈希已核对 |
| 普通用户权限 | 当前本地桌面用户通过 logind/uaccess 获得三个指定设备的读写 ACL；其他用户权限为 `---`，未设为所有人可写 |
| 无显示硬解 | 普通用户解码 15 秒、1080p30、450 帧 H.264；Cedar 中断增加 450，正常 EOS，约 3.32 秒完成 |
| 实际显示 | 在测试程序创建的 1920×1080 X11 窗口中播放同一片段；450 帧 rendered、0 帧 dropped、中断增加 450，正常 EOS；总耗时 15.26 秒 |
| 调试显示复测 | 同一管线加入详细调试与截图后，449 帧 rendered、1 帧 dropped；单独记录，不混用作无丢帧结论 |
| 可见区域 | 输出 YV12、1920×1088，对齐区域由动态 `GstVideoCropMeta` 指示的 1920×1080 可见区域裁去；XVideo 调试日志确认使用该裁剪 |
| 像素正确性 | 对硬解原始帧按元数据裁剪并规范 YV12 顺序后，1080p 首帧与 FFmpeg 软件解码逐字节相同；另一份短片的 29 帧也完全相同 |

上述显示帧数来自不含截图或详细调试的独立测试。它证明本次 H.264 片段可实时播放，
不能据此保证所有视频、分辨率或未来滚动版本。

## 已验证的管线

在获得设备 ACL 的本地桌面用户会话中，可使用下面的相同元素顺序播放 **H.264 MP4 本地文件**：

```sh
a7z-vpu-run gst-launch-1.0 -e \
  filesrc location="/absolute/path/video.mp4" \
  ! qtdemux ! h264parse ! omxh264dec \
  ! queue max-size-buffers=4 max-size-bytes=0 max-size-time=0 \
  ! xvimagesink name=screen sync=true force-aspect-ratio=true
```

精确的 1920×1080 显示测试由测试程序预先创建 X11 窗口，再通过 `GstVideoOverlay`
交给 `xvimagesink`。直接运行上面的 `gst-launch-1.0` 时，OMX 的初始小尺寸协商
可能让自动创建的窗口较小，可以手动调整窗口；这不表示解码分辨率降为窗口初始尺寸。

也验证过 `omxh264dec disable-dma-feature=true` 的 SystemMemory 输出：
小窗口测试约 29.95 fps，未报告丢帧。最终大窗口测试使用上面的默认解码器配置及
四帧队列。未将固定 `bottom=8` 的裁剪或全局 EGL 环境写入系统。

## 已知边界

- 这是一条外部 GStreamer 播放管线。Chromium 当前仍使用软件视频解码；网页
  ANGLE/Vulkan 加速与 VPU 硬解分别验证，不能互相代替。接口缺口见
  [Chromium 适配说明](CHROMIUM-INTEGRATION.zh-CN.md)。
- `xvimagesink` 显示路径明确发生了缓冲区复制，因此不声称从解码到屏幕全程零拷贝。
- XVideo 正确读取动态裁剪区域，但其强制宽高比计算仍使用协商的 1920×1088，
  与可见 1920×1080 的比例存在约 0.7% 差异。像素比对证明的是裁剪后的原始
  解码帧正确，并不等于整个显示缩放链逐像素一致。
- 本测试片不含音轨；音频、音画同步、seek、长时间播放、其他编码格式以及
  `playbin3` 自动选解码器均未在本轮验收。
- 原厂库会输出若干配置缺失、格式枚举及日志级别信息；本轮以正常 EOS、
  完整帧数、Cedar 中断和像素比对确认成功，不以日志标签单独判断硬解是否生效。

本记录独立于已构建包，保留 `0.1.0-1` 包内 README、文件字节和原始校验值。

## 上游依据

[Radxa 官方视频管线](https://docs.radxa.com/en/cubie/a7z/app-dev/video-codec) 使用 OMX 与 XVideo。
[GStreamer 1.28.7 的 XVideo 实现](https://github.com/GStreamer/gstreamer/blob/1.28.7/subprojects/gst-plugins-base/sys/xvimage/xvimagesink.c)
读取并在复制路径保留裁剪元数据；显示比例计算与缓冲区复制的边界也来自该实现。
