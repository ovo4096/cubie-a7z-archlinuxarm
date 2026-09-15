# 桌面与中文输入默认设置

`v0.2.2-t5` 的 CLI、XFCE / LightDM 和 KDE / SDDM 共用 HDMI 内核修复，
移除旧桌面启动恢复钩子，保留真实 HPD 检测和原有 GPU 配置。
此前 CLI 补丁已确认两次启动与一次真实拔插；本次新包、桌面和新镜像没有新增测试。
详情与限制见 [HDMI 说明](HDMI.zh-CN.md)。中文输入与浏览器配置没有改动，以下保留原有说明。

XFCE 与 KDE 镜像预装 Fcitx 5 + Rime，默认方案是 **朙月拼音·简化字**
（`luna_pinyin_simp`）。初始状态为英文，按 **Ctrl+Space** 切换中文；
输入拼音后按空格选择候选字。首次登录后，Rime 会在用户目录部署方案，
首次启用可能需要等待片刻。菜单中的 Fcitx 5 配置工具可调整输入法与快捷键。
方案本身由官方 `rime-luna-pinyin` 提供并默认输出简化字。
[Rime 方案源码](https://github.com/rime/rime-luna-pinyin/blob/master/luna_pinyin_simp.schema.yaml)

构建使用 Arch Linux ARM 官方仓库的 `fcitx5`、`fcitx5-rime`、
`fcitx5-gtk`、`fcitx5-qt`、`fcitx5-configtool`、`rime-luna-pinyin`，
以及桌面已有的 `noto-fonts-cjk`、`noto-fonts-emoji`、`ttf-dejavu`。
GTK、Qt 与 XIM 的变量只在 X11 图形会话设置；自动启动文件复制自已安装的
官方 `org.fcitx.Fcitx5.desktop`。KDE 镜像使用 Plasma X11，额外保留其官方支持的
`plasma-workspace/env` 环境入口。
[Fcitx 5 设置指南](https://fcitx-im.org/wiki/Setup_Fcitx_5)

图形会话使用 `zh_CN.UTF-8`，字体预设提供简体中文与 Emoji 回退。
全局 `locale.conf` 缺失时使用 `C.UTF-8`；已有设置保持原样。
串口、TTY 与 CLI 镜像不切换为中文，避免控制台中文字形缺失。
这些默认值针对目前的 X11 镜像；改用 Wayland 后需要根据桌面协议重新设置输入法。
[Fcitx Wayland 指南](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland/en)

HTTP、HTTPS、HTML 与 XHTML 默认关联 **Chromium（PowerVR）**。
应用菜单入口由 GPU 包安装；它使用项目的 `a7z-chromium` 启动器。
XFCE 另设浏览器 helper，使面板上的“网页浏览器”按钮也使用这个入口。
helper 的类型、类别与带参数命令沿用 XFCE 官方格式。
[XFCE helper 实现](https://github.com/xfce-mirror/xfce4-settings/blob/master/dialogs/mime-settings/xfce-mime-helper.c)
目前的 Plasma 与 KIO 直接查询 HTTP/HTTPS 默认 MIME 应用，沿用同一份
`mimeapps.list` 即可，不额外设置旧版的 `BrowserApplication` 键。
[Plasma 默认浏览器查询](https://github.com/KDE/plasma-workspace/blob/master/libtaskmanager/tasktools.cpp)，
[KIO 浏览器查询](https://github.com/KDE/kio/blob/master/src/gui/openurljob.cpp)
如需改用其他浏览器，可在桌面的默认应用设置中修改。
Chromium 自身的“设为默认”可能关联普通 `chromium.desktop`，因此要保留
PowerVR 入口时，应从系统默认应用设置中选择 Chromium（PowerVR）。

`tools/desktop.py` 提供纯离线接口：

```python
configure_desktop_defaults(root: Path, variant: str, user: str = "alarm") -> dict
```

调用前需安装 Fcitx 5 与 GPU 包的桌面入口；调用后，GUI 镜像需在 chroot 内运行
`locale-gen`，再由发布清理流程从 `/etc/skel` 生成干净的用户目录。
返回值中的 `locale_gen_changed` 仅表示生成列表有变化，并不保证 locale 已编译。
CLI 调用不写任何文件。

所有用户预设只写入 `/etc/skel`。已有同名配置或禁用的自动启动文件保持原样，
该模块不修改现有 home。Rime 只包含静态 `default.custom.yaml`，不预运行输入法，
不打包学习词库、用户词频、安装标识或部署缓存；个人数据在用户首次使用后生成。
自定义采用上游推荐的 `.custom.yaml` 补丁形式，不覆盖官方词库与方案。
[Rime 定制指南](https://github.com/rime/home/wiki/CustomizationGuide)

开发者可按以下命令进行离线验证；v0.2.2 发布没有执行此测试：

```sh
python3 -m unittest discover -s tests -p test_desktop_defaults.py -v
```

测试涵盖 CLI 零改动、已有设置保留、重复执行、符号链接隔离、干净的静态输入法
种子以及 X11/Wayland/TTY 环境边界。它们不替代镜像启动后的 GTK、Qt 与 Chromium
中文输入实机检查。
