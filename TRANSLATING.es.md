[English](TRANSLATING.md) | **Español** | [Français](TRANSLATING.fr.md) | [Deutsch](TRANSLATING.de.md) | [Українська](TRANSLATING.uk.md) | [हिन्दी](TRANSLATING.hi.md) | [日本語](TRANSLATING.ja.md) | [中文](TRANSLATING.zh.md)

# Traducir Orcshot

Actualmente Orcshot se distribuye en estos idiomas:

- Inglés (predeterminado: siempre disponible, no necesita archivo de traducción)
- Español
- Français
- Deutsch
- Українська
- हिन्दी
- 日本語
- 中文

Si su idioma no está en esa lista, o si ha detectado una traducción incorrecta,
poco natural o que falta, esta página es para usted. **No necesita saber
programar ni tiene que mirar ningún código fuente.**

## Lo que necesita

Una sola herramienta gratuita: [Poedit](https://poedit.net/) (Windows, Mac y
Linux). Es el editor estándar para este tipo de archivos de traducción y le
muestra una sencilla lista de dos columnas: el texto original en inglés a la
izquierda y un espacio en blanco para su traducción a la derecha. Sin código y
sin sintaxis que aprender.

## Añadir un idioma nuevo

1. Descargue el archivo de plantilla: [`po/orcshot.pot`](po/orcshot.pot).
2. Ábralo en Poedit.
3. Cuando Poedit se lo pregunte, elija «Crear nueva traducción» y seleccione su idioma.
4. Recorra la lista y escriba una traducción para cada cadena en inglés de la
   izquierda.
5. Guarde el archivo: Poedit lo guardará como `<código-de-su-idioma>.po` (por
   ejemplo, `it.po` para el italiano).
6. Envíelo de vuelta (consulte «Cómo enviarlo de vuelta» más abajo).

## Mejorar una traducción existente

1. Descargue el archivo de ese idioma desde [`po/`](po/) (por ejemplo,
   [`po/es.po`](po/es.po) para el español).
2. Ábralo en Poedit y edite las entradas que haya que corregir.
3. Guárdelo y envíelo de vuelta de la misma manera.

## Un detalle al que prestar atención

Algunas cadenas contienen un marcador de posición `{}`, como esta:

```
"You're running the latest version ({})."
```

Ese `{}` se sustituye por otra cosa en tiempo de ejecución (un número de
versión, un nombre de archivo, etc.): consérvelo en su traducción y limítese a
moverlo al lugar que le corresponda de forma natural según el orden de la frase
en su idioma. Poedit le avisará si a una traducción le falta un marcador de
posición que sí tiene el original, lo cual es una buena señal de que algo
merece una segunda revisión.

También verá algunas cadenas que son nombres propios (el propio «Orcshot») o
solo símbolos y números: estas deben quedarse tal cual y no deberían necesitar
traducción alguna.

## Cómo enviarlo de vuelta

**Si se maneja bien con GitHub:** abra un pull request que añada o actualice su
archivo en `po/`. Eso es todo: no hay que cambiar ningún otro archivo.

**Si no:** no pasa nada. Simplemente
[abra una incidencia](https://github.com/artificialorctelligence/orcshot/issues/new)
y adjunte su archivo `.po`. Si prefiere no usar GitHub en absoluto, puede
enviarlo por correo electrónico a <orc.shot@yahoo.com>. En cualquier caso,
alguien abrirá el pull request por usted.

## Qué ocurre después

Una persona del equipo de mantenimiento revisará la traducción (idealmente con
la ayuda de otro hablante de ese idioma, ya que la calidad de la traducción
importa y ninguno de nosotros verifica personalmente todos los idiomas), la
fusionará y se incluirá en la siguiente versión.
