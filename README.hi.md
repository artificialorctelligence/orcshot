[English](README.md) | [Español](README.es.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Українська](README.uk.md) | **हिन्दी** | [日本語](README.ja.md) | [中文](README.zh.md)

# Orcshot

[Greenshot](https://getgreenshot.org/) का एक Linux पोर्ट, जिसे Python + GTK3 में व्यवहार के स्तर पर
निष्ठापूर्वक पोर्ट किया गया है - यह Greenshot परियोजना से संबद्ध नहीं है और न ही उसके द्वारा समर्थित है।
पूरे दायरे, प्लेटफ़ॉर्म प्राथमिकताओं और आर्किटेक्चर संबंधी निर्णयों के लिए
[REQUIREMENTS.md](REQUIREMENTS.md) देखें।

## इंस्टॉल करना

**PPA से** (Ubuntu 24.04 LTS, Ubuntu 26.04 LTS, और Linux Mint जैसे Ubuntu-आधारित डिस्ट्रो):

```
sudo add-apt-repository ppa:artificialorctelligence/orcshot
sudo apt update
sudo apt install orcshot
```

**सोर्स से** (कोई भी अन्य Debian-आधारित डिस्ट्रो, या अगर आप इसे खुद बनाना चाहें):

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

किसी भी तरीके से, यह एक सामान्य Debian पैकेज है - इंस्टॉल होने के बाद यह किसी भी दूसरे ऐप की तरह
व्यवहार करता है (आपके एप्लिकेशन मेन्यू में दिखता है, `apt remove` से साफ़-सुथरे तरीके से अनइंस्टॉल हो
जाता है, वग़ैरह)। इन पर सत्यापित: Linux Mint (Cinnamon), Ubuntu 24.04 LTS और Ubuntu 26.04 LTS।

पहली बार Orcshot शुरू करने पर यह कैप्चर के लिए कीबोर्ड शॉर्टकट और लॉगिन-पर-शुरू सेट करने की पेशकश
करता है (शॉर्टकट सिर्फ़ Cinnamon पर - दूसरे डेस्कटॉप के लिए `debian/control` में दिया गया नोट देखें)।
आप इसे ट्रे आइकन की प्राथमिकताएँ से कभी भी दोबारा देख सकते हैं।

बाद में अपडेट करने के लिए: `sudo apt update && sudo apt upgrade` (PPA इंस्टॉल के लिए), या नवीनतम
बदलाव pull करें और दोबारा बिल्ड/इंस्टॉल करें (सोर्स से) - दोबारा इंस्टॉल करने से आपकी कीबाइंडिंग,
ऑटोस्टार्ट सेटिंग या कोई भी दूसरी प्राथमिकता कभी नहीं बदलती, वे पैकेज में नहीं, आपके अपने उपयोगकर्ता
कॉन्फ़िग में रहती हैं। मदद > अपडेट देखें भी आपको बता देगा कि कोई नया संस्करण कब उपलब्ध है।

## डेवलपमेंट सेटअप

```
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

PyGObject को बिल्ड करने के लिए इन सिस्टम पैकेजों की ज़रूरत होती है: `libcairo2-dev`,
`libgirepository-2.0-dev`, `libgtk-3-dev`।

## टेस्ट चलाना

```
.venv/bin/pytest
```
