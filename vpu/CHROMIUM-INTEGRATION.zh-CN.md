# 当前 Chromium 的视频接口缺口

2026-09-15 的实机结果将两层能力分开验证：当前 Arch Chromium 153 通过 ANGLE/
Vulkan 使用 PowerVR 渲染网页，Arch GStreamer 1.28.7 通过官方 OMX/Cedar 使用
A733 的专用视频引擎解码 H.264。二者分别有效，但当前浏览器没有连接到后者。

## 官方 T5 的连接方式

锁定 T5 的 dpkg manifest 包含 `chromium-browser-sunxi 120.0.6099.224-6`。
该二进制的 DT_NEEDED 含 GStreamer 的 core/app/video 库，字符串包含
`VmxGstVideoDecoder`、`src/media/filters/vmx_gst_video_decoder.cc`、
`omxh264dec`、`omxhevcvideodec`、`kVmxCedarc`。这些证据支持官方使用
Chromium 定制解码器 → GStreamer → OpenMAX → Cedar 的判断。

检查的 [allwinner-debian 包目录](https://github.com/radxa/allwinner-debian/tree/main/packages/arm64)
提供 Chromium/GStreamer/Cedar 的 Debian 二进制包；
[allwinner-prebuilt](https://github.com/radxa-pkg/allwinner-prebuilt) 的源码子模块也指向该仓库。
在这些公开仓库、包内文档和本次官方来源检索中，未找到对应 `VmxGstVideoDecoder`
的可直接移植补丁。包内 Chromium copyright 只指向通用 Chromium 上游，不能据此
取得 Allwinner 的定制实现。这里不把“未找到”表述为“源码不存在”。

当前 [Chromium 153 Linux 视频后端](https://github.com/chromium/chromium/blob/153.0.8010.36/media/gpu/BUILD.gn)
源码具备 VA-API/V4L2 等可选接口，具体是否编入取决于打包参数；
[filters 构建配置](https://github.com/chromium/chromium/blob/153.0.8010.36/media/filters/BUILD.gn)
没有上述 Vmx/GStreamer 入口。板上只有 `cedar_dev` 这类厂商字符设备，当前没有
可供这一用途使用的 V4L2 解码设备，也没有 A733 VA-API 后端。安装 `libva` 或
添加 `--enable-features=...` 不能实现缺少的接口。

## 可落地的后续路线

1. **取得厂商 Chromium 定制补丁并移植到当前版本。** 需要适配当前 VideoDecoder/
   VideoFrame 生命周期、输出 crop/stride、时间戳与 seek/flush，保持浏览器沙箱，
   并处理 Cedar 与渲染进程之间的 DMABuf 传递。已有 GStreamer 硬解结果可作对照。
   这需要重新构建 Chromium，不能把旧 120 的库文件复制到 153 中完成。
2. **实现独立 Cedar VA-API 或 V4L2 适配层。** 优点是可服务多个当前应用；需要适配
   参数/码流提交、帧引用与重排、解码表面、DMABuf 导出和同步，以及浏览器设备访问
   的沙箱规则。这是新的驱动接口工程，不能用目前支持其他 Allwinner 代际的 Cedrus
   驱动或通用 `libva` 直接替代。至少先以 H.264 像素/帧数/seek/重启测试验收，
   再扩展其他编码格式。

当前可保留持续更新的 Chromium 用于网页，并让可选 GStreamer 工具处理本地硬解播放。
这种外部播放方式应明确标示，不能计为 Chromium 内的视频硬解。官方 Chromium 120
可作为隔离的本地参考实验，本项目没有把它安装成日常浏览器。
