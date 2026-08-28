[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | [日本語](README.ja.md) | **中文**

# Orcshot

**快速安装**（Ubuntu 24.04/26.04、Mint 及其他基于 Ubuntu 的发行版）：
```bash
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update && sudo apt install orcshot
```

[Greenshot](https://getgreenshot.org/) 的 Linux 移植版，用 Python + GTK3 忠实还原其行为——本项目与
Greenshot 项目没有从属关系，也未获得其认可。本项目与 [Apache ORC](https://orc.apache.org/) 项目也没有
任何关系——名称中同样出现的"Orc"纯属巧合。完整的功能范围、平台优先级和架构决策请参阅
[REQUIREMENTS.md](REQUIREMENTS.md)。

## 安装

**通过 PPA**（Ubuntu 24.04 LTS、Ubuntu 26.04 LTS，以及 Linux Mint 等基于 Ubuntu 的发行版）：

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**从源代码构建**（其他任何基于 Debian 的发行版，或者您想自行构建）：

```
sudo apt install dpkg-dev debhelper dh-python pybuild-plugin-pyproject python3-all \
    python3-hatchling python3-pytest python3-hypothesis python3-scipy python3-gi \
    python3-gi-cairo python3-cairo python3-numpy python3-shapely python3-xlib \
    gir1.2-gtk-3.0 gir1.2-rsvg-2.0 gir1.2-gdkpixbuf-2.0 gir1.2-pango-1.0 gir1.2-glib-2.0

git clone https://github.com/artificialorctelligence/orcshot.git
cd orcshot
dpkg-buildpackage -us -uc -b
sudo apt install ../orcshot_*_all.deb
```

无论哪种方式，它都是一个普通的 Debian 软件包——安装之后，它的表现与其他任何应用无异（会出现在应用
程序菜单中，可用 `apt remove` 干净地卸载，等等）。已在以下系统上验证：Linux Mint（Cinnamon）、
Ubuntu 24.04 LTS 和 Ubuntu 26.04 LTS。

首次启动 Orcshot 时，它会提示您设置截图快捷键以及登录时自动启动（快捷键仅支持 Cinnamon——其他桌面
环境请参阅 `debian/control` 中的说明）。您随时可以从托盘图标的“首选项”中重新进行设置。

日后更新：`sudo apt update && sudo apt upgrade`（PPA 安装方式），或拉取最新改动后重新构建/安装
（源代码方式）——重新安装绝不会改动您的快捷键、自动启动设置或任何其他首选项，它们保存在您自己的
用户配置中，而不在软件包里。“帮助 > 检查更新”也会在有更新版本可用时告知您。

## 开发环境搭建

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

需要用于构建 PyGObject 的系统软件包：`libcairo2-dev`、`libgirepository-2.0-dev`、
`libgtk-3-dev`。

## 运行测试

```
.venv/bin/pytest
```
