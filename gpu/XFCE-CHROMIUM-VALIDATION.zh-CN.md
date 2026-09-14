# XFCE 与 Chromium 实机验证（2026-09-15）

本次验证对象是 T5 SD 系统、XFCE 4.20、Arch Chromium `153.0.8010.36-1`。
内核 `6.6.98-4-aw2511`，Mesa `26.2.2-1`，GStreamer `1.28.7`。
GPU 用户态升级到 `radxa-a7z-gpu-userspace 24.2.6603887_t5-5`；
其 20 个私有驱动 ELF 文件在事务前后逐个 SHA256 相同。

这些增量已在实机安装，源码包含新的启动器和可选 VPU 包配方。
**已经发布的 `v0.1.0-t5` 六个镜像没有被重新生成或替换，不包含本次增量。**

## XFCE 桌面

`xfwm4` 的 `use_compositing=true`、`vblank_mode=auto`。实际持有
`_NET_WM_CM_S0` 合成管理器选择项，并向其合成输出窗口提交 XPresent；
8 秒受控移动窗口实验观察到 358 个真实 PresentComplete 事件，MSC/UST 持续前进。
XRender 合成由启用 PowerVR glamor 的 Xorg 执行，不能因 xfwm4 自身没有映射
厂商 GPU 库就判定整个桌面在 CPU 上合成。

本机的 GLX/llvmpipe 路径被 xfwm4 拒绝后，默认 auto 已选用 XPresent。
没有更改桌面合成参数，没有安装额外合成器。
这不代表所有 GTK 控件、应用和视频都会自动使用 GPU。

## Chromium 网页绘制

[a7z-chromium](CHROMIUM.zh-CN.md) 通过原 Arch 启动器选择 ANGLE Vulkan、
PowerVR ICD 和三个 Vulkan feature。实机 renderer 为
`ANGLE (Imagination Technologies, Vulkan 1.3.277 (PowerVR B-Series BXM-4-64 MC1))`。
Canvas、GPU compositing、rasterization、WebGL/WebGL2 均通过；两个 WebGL
上下文实际绘制并读回像素 `[64,128,191,255]`，无 GL 错误。

1920×1080 页面、48 个半透明 CSS transform 元素、12 秒动画、前 2 秒预热，
两次受控比较期间不运行 VPU 测试：

| 指标 | 原始 Chromium 启动 | PowerVR Vulkan 启动 |
|---|---:|---:|
| 平均 requestAnimationFrame 间隔 | 28.26 ms | 16.67 ms |
| 第 95 百分位间隔 | 50.0 ms | 16.7 ms |
| 大于 25 ms 的间隔 | 203 | 0 |
| Chromium 进程 CPU，单核为 100% | 154.1% | 110.3% |

这是短时合成页面的回调间隔与进程 CPU，不能外推为所有网页帧率或端到端显示延迟。
正式安装包的启动器又独立完成绘制和视频播放检查；软件回退实际使 GPU
compositing、raster 和 WebGL 关闭。

启动器没有加入 `--no-sandbox`、`--disable-gpu-sandbox` 或
`--ignore-gpu-blocklist`。renderer 保持 Seccomp 过滤和 PID/网络命名空间；
`chrome://sandbox` 报告浏览器沙箱可用。GPU 进程在本机原始启动和 Vulkan
启动下都没有 Seccomp 过滤，不能把网页 renderer 的结果当成 GPU 进程沙箱证明。

## 浏览器视频的当前限制

自行生成的 15 秒 1080p30 H.264 High 测试片共 450 帧，安装后的启动器完整播放，
`getVideoPlaybackQuality()` 记录 450 帧、0 丢帧。但媒体日志明确报告：

```text
kVideoDecoderName = FFmpegVideoDecoder
kIsPlatformVideoDecoder = false
video_decode = disabled_software
```

因此目前是 GPU 网页绘制配合 CPU 视频解码，**Chromium 内硬件视频解码尚未完成**。
VPU 本身与 GStreamer 的验证见 [独立 VPU 验收](../vpu/VALIDATION.zh-CN.md)，
浏览器缺失的接口及后续工作见 [Chromium 视频接口](../vpu/CHROMIUM-INTEGRATION.zh-CN.md)。

## 维护范围

本次先完成完整 `pacman -Syu --needed` 安装 GStreamer 依赖，事务中新装多媒体包，
已有包只有 tzdata 和 libtirpc 跨版本更新；这不是跨版本 Chromium/Mesa 升级试验。
随后安装 GPU 启动器包和可选 VPU 包。Chromium、Xorg、Mesa、libglvnd、两个项目
用户态包的 `pacman -Qkk` 均为零修改，系统无失败 unit。

未来 Chromium、ANGLE、Mesa 或 GStreamer ABI/行为更新后，需要重复真实绘制、
媒体解码器、视频像素与设备中断检查。当前测试不能保证任意未来版本兼容。

上游参考：[xfwm4 合成实现](https://github.com/xfce-mirror/xfwm4/blob/xfwm4-4.20.0/src/compositor.c)、
[Xorg glamor](https://www.x.org/Development/Documentation/GlamorPerformance/)。
