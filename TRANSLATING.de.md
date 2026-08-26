[English](TRANSLATING.md) | [Español](TRANSLATING.es.md) | [Français](TRANSLATING.fr.md) | **Deutsch** | [Українська](TRANSLATING.uk.md) | [हिन्दी](TRANSLATING.hi.md) | [日本語](TRANSLATING.ja.md) | [中文](TRANSLATING.zh.md)

# Orcshot übersetzen

Orcshot wird derzeit in diesen Sprachen ausgeliefert:

- Englisch (Standard – immer verfügbar, benötigt keine Übersetzungsdatei)
- Español
- Français
- Deutsch
- Українська
- हिन्दी
- 日本語
- 中文

Wenn Ihre Sprache nicht in dieser Liste steht oder Ihnen eine Übersetzung
aufgefallen ist, die falsch, holprig oder gar nicht vorhanden ist – dann ist
diese Seite für Sie. **Sie müssen nicht programmieren können, und Sie müssen
sich keinerlei Quellcode ansehen.**

## Was Sie brauchen

Nur ein einziges kostenloses Werkzeug: [Poedit](https://poedit.net/) (Windows,
Mac und Linux). Es ist der Standardeditor für diese Art von Übersetzungsdatei
und zeigt Ihnen eine einfache zweispaltige Liste – links den englischen
Originaltext, rechts ein leeres Feld für Ihre Übersetzung. Kein Code, keine
Syntax, die man lernen müsste.

## Eine neue Sprache hinzufügen

1. Laden Sie die Vorlagendatei herunter: [`po/orcshot.pot`](po/orcshot.pot).
2. Öffnen Sie sie in Poedit.
3. Wählen Sie, wenn Poedit danach fragt, „Neue Übersetzung erstellen“ und
   dann Ihre Sprache aus.
4. Gehen Sie die Liste durch und tragen Sie für jeden englischen Text auf der
   linken Seite eine Übersetzung ein.
5. Speichern Sie die Datei – Poedit speichert sie als `<Ihr-Sprachcode>.po`
   (zum Beispiel `it.po` für Italienisch).
6. Schicken Sie sie zurück (siehe „Zurückschicken“ weiter unten).

## Eine bestehende Übersetzung verbessern

1. Holen Sie sich die Datei für die betreffende Sprache aus [`po/`](po/) (zum
   Beispiel [`po/es.po`](po/es.po) für Spanisch).
2. Öffnen Sie sie in Poedit und bearbeiten Sie die Einträge, die korrigiert
   werden müssen.
3. Speichern Sie sie und schicken Sie sie auf demselben Weg zurück.

## Worauf Sie achten sollten

Manche Texte enthalten einen Platzhalter `{}`, zum Beispiel so:

```
"You're running the latest version ({})."
```

Dieses `{}` wird zur Laufzeit durch etwas anderes ersetzt (eine Versionsnummer,
einen Dateinamen usw.) – bitte behalten Sie es in Ihrer Übersetzung bei und
verschieben Sie es einfach dorthin, wo es in der Satzstellung Ihrer Sprache
natürlich hingehört. Poedit warnt Sie, wenn in einer Übersetzung ein
Platzhalter fehlt, den das Original enthält – ein gutes Zeichen dafür, dass
etwas noch einmal geprüft werden sollte.

Ihnen werden außerdem ein paar Texte begegnen, die Eigennamen sind („Orcshot“
selbst) oder reine Symbole bzw. Zahlen – diese sollen unverändert bleiben und
müssen gar nicht übersetzt werden.

## Zurückschicken

**Wenn Sie sich mit GitHub auskennen:** Öffnen Sie einen Pull Request, der Ihre
Datei unter `po/` hinzufügt oder aktualisiert. Das war's – keine weiteren
Dateien müssen geändert werden.

**Wenn nicht:** Das ist völlig in Ordnung. Sie können einfach
[ein Issue öffnen](https://github.com/artificialorctelligence/orcshot/issues/new)
und Ihre `.po`-Datei anhängen. Wenn Sie GitHub gar nicht nutzen möchten,
können Sie sie stattdessen per E-Mail an <orc.shot@yahoo.com> schicken. So oder
so wird jemand den Pull Request für Sie öffnen.

## Was danach passiert

Ein Maintainer sieht sich die Übersetzung an (idealerweise mit Hilfe einer
weiteren Person, die diese Sprache spricht, denn Übersetzungsqualität ist
wichtig und niemand von uns überprüft persönlich jede Sprache), führt sie ein
und sie wird mit der nächsten Veröffentlichung ausgeliefert.
