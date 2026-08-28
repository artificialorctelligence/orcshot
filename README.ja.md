[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Українська](README.uk.md) | [हिन्दी](README.hi.md) | **日本語** | [中文](README.zh.md)

# Orcshot

[Greenshot](https://getgreenshot.org/) の Linux 移植版で、Python + GTK3 による忠実な動作の移植として作られています。Greenshot プロジェクトとの提携関係はなく、同プロジェクトによる承認も受けていません。また、[Apache ORC](https://orc.apache.org/) プロジェクトとも関係がなく、名前に含まれる「Orc」の一致は偶然です。全体の対応範囲、プラットフォームの優先順位、アーキテクチャ上の決定については [REQUIREMENTS.md](REQUIREMENTS.md) を参照してください。

## インストール

**PPA から**（Ubuntu 24.04 LTS、Ubuntu 26.04 LTS、および Linux Mint など Ubuntu ベースのディストリビューション向け）:

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**ソースから**（その他の Debian ベースのディストリビューション、または自分でビルドしたい場合）:

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

どちらの方法でも、ごく普通の Debian パッケージなので、インストール後は他のアプリと同じように扱えます（アプリケーションメニューに表示され、`apt remove` できれいにアンインストールできます）。動作確認済みの環境: Linux Mint (Cinnamon)、Ubuntu 24.04 LTS、Ubuntu 26.04 LTS。

Orcshot を初めて起動すると、キャプチャ用のキーボードショートカットとログイン時の自動起動を設定するか尋ねられます（ショートカットの自動設定に対応しているのは Cinnamon のみです。他のデスクトップ環境については `debian/control` の注記を参照してください）。この設定は、トレイアイコンの「設定」からいつでも変更できます。

後で更新する場合: `sudo apt update && sudo apt upgrade`（PPA でインストールした場合）、または最新の変更を取得してビルドし直し、再インストールします（ソースからの場合）。再インストールしても、キーバインド、自動起動の設定、その他の設定が変更されることはありません。これらはパッケージではなく、ユーザー自身の設定に保存されています。「ヘルプ」>「更新を確認」でも新しいバージョンの有無を確認できます。

## 開発環境のセットアップ

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

PyGObject をビルドするために、次のシステムパッケージが必要です: `libcairo2-dev`、`libgirepository-2.0-dev`、`libgtk-3-dev`。

## テストの実行

```
.venv/bin/pytest
```
