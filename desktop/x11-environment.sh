# A7Z image default: source only for an X11 graphical login.
# LightDM/SDDM read ~/.xprofile; Plasma also reads its env directory.
if [ -n "${DISPLAY:-}" ] && [ "${XDG_SESSION_TYPE:-x11}" = x11 ]; then
    unset LC_ALL
    export LANG=zh_CN.UTF-8
    export LANGUAGE=zh_CN:zh:en_US:en
    export GTK_IM_MODULE=fcitx
    export QT_IM_MODULE=fcitx
    export XMODIFIERS=@im=fcitx
fi
