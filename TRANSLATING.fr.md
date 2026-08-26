[English](TRANSLATING.md) | [Español](TRANSLATING.es.md) | **Français** | [Deutsch](TRANSLATING.de.md) | [Українська](TRANSLATING.uk.md) | [हिन्दी](TRANSLATING.hi.md) | [日本語](TRANSLATING.ja.md) | [中文](TRANSLATING.zh.md)

# Traduire Orcshot

Orcshot est actuellement livré dans ces langues :

- Anglais (par défaut - toujours disponible, ne nécessite aucun fichier de traduction)
- Español
- Français
- Deutsch
- Українська
- हिन्दी
- 日本語
- 中文

Si votre langue ne figure pas dans cette liste, ou si vous avez repéré une
traduction erronée, maladroite ou manquante - cette page est pour vous. **Vous
n'avez pas besoin de savoir programmer, ni de consulter le moindre code
source.**

## Ce dont vous avez besoin

Un seul outil gratuit : [Poedit](https://poedit.net/) (Windows, Mac et Linux).
C'est l'éditeur standard pour ce type de fichier de traduction, et il vous
présente une simple liste à deux colonnes - le texte anglais d'origine à
gauche, et un espace vide pour votre traduction à droite. Pas de code, aucune
syntaxe à apprendre.

## Ajouter une nouvelle langue

1. Téléchargez le fichier modèle : [`po/orcshot.pot`](po/orcshot.pot).
2. Ouvrez-le dans Poedit.
3. Lorsque Poedit vous le demande, choisissez « Créer une nouvelle traduction »
   et sélectionnez votre langue.
4. Parcourez la liste et saisissez une traduction pour chaque chaîne anglaise
   de la colonne de gauche.
5. Enregistrez le fichier - Poedit l'enregistrera sous le nom
   `<code-de-votre-langue>.po` (par exemple `it.po` pour l'italien).
6. Renvoyez-le (voir « Renvoyer votre fichier » ci-dessous).

## Améliorer une traduction existante

1. Récupérez le fichier de cette langue dans [`po/`](po/) (par exemple
   [`po/es.po`](po/es.po) pour l'espagnol).
2. Ouvrez-le dans Poedit et modifiez les entrées qui ont besoin d'être
   corrigées.
3. Enregistrez, puis renvoyez-le de la même manière.

## Un seul fichier couvre tout

Sur un bureau Wayland, le menu de l'icône de la zone de notification
d'Orcshot est dessiné par un composant distinct (une extension GNOME Shell)
plutôt que par l'application principale, mais il réutilise exactement les
mêmes traductions. Vous n'avez rien à faire différemment ni à remplir un
second fichier : traduire `po/<lang>.po` couvre automatiquement le menu de
la zone de notification, aussi bien sous X11 que sous Wayland.

## Un point de vigilance

Certaines chaînes contiennent un espace réservé `{}`, comme ceci :

```
"You're running the latest version ({})."
```

Ce `{}` est remplacé par autre chose à l'exécution (un numéro de version, un
nom de fichier, etc.) - veuillez le conserver dans votre traduction, en le
déplaçant simplement là où il se place naturellement dans l'ordre des mots de
votre langue. Poedit vous avertira si une traduction ne contient pas un espace
réservé présent dans l'original, ce qui est un bon indice qu'il faut y regarder
à deux fois.

Vous verrez aussi quelques chaînes qui sont des noms propres (« Orcshot »
lui-même) ou de purs symboles ou chiffres - celles-ci doivent rester telles
quelles et ne nécessitent aucune traduction.

## Renvoyer votre fichier

**Si vous êtes à l'aise avec GitHub :** ouvrez une pull request qui ajoute ou
met à jour votre fichier dans `po/`. C'est tout - aucun autre fichier n'a
besoin d'être modifié.

**Sinon :** aucun problème. Il vous suffit
d'[ouvrir un ticket](https://github.com/artificialorctelligence/orcshot/issues/new)
et d'y joindre votre fichier `.po`. Si vous préférez ne pas utiliser GitHub du
tout, vous pouvez à la place l'envoyer par e-mail à <orc.shot@yahoo.com>. Dans
tous les cas, quelqu'un ouvrira la pull request à votre place.

## Ce qui se passe ensuite

Un mainteneur relira la traduction (idéalement avec l'aide d'une autre personne
parlant cette langue, car la qualité des traductions compte et aucun d'entre
nous ne vérifie personnellement chaque langue), l'intégrera, et elle sera
livrée dans la prochaine version.
