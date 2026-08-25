# Translating Orcshot

Orcshot currently ships in these languages:

- English (default - always available, needs no translation file)
- Spanish
- French
- German
- Ukrainian
- Hindi
- Japanese
- Chinese

If your language isn't in that list, or you've spotted a translation that's
wrong, awkward, or missing - this page is for you. **You do not need to know
how to program, and you do not need to look at any source code.**

## What you need

Just one free tool: [Poedit](https://poedit.net/) (Windows, Mac, and Linux).
It's the standard editor for this kind of translation file, and it gives you
a simple two-column list - the original English text on the left, and a
blank space for your translation on the right. No code, no syntax to learn.

## Adding a new language

1. Download the template file: [`po/orcshot.pot`](po/orcshot.pot).
2. Open it in Poedit.
3. When Poedit asks, choose "Create new translation" and pick your language.
4. Go through the list and fill in a translation for each English string on
   the left.
5. Save the file - Poedit will save it as `<your-language-code>.po` (for
   example `it.po` for Italian).
6. Send it back (see "Sending it back" below).

## Improving an existing translation

1. Grab the file for that language from [`po/`](po/) (for example
   [`po/es.po`](po/es.po) for Spanish).
2. Open it in Poedit and edit whichever entries need fixing.
3. Save, then send it back the same way.

## One thing to watch for

Some strings contain a `{}` placeholder, like this:

```
"You're running the latest version ({})."
```

That `{}` gets replaced with something else at runtime (a version number, a
file name, etc.) - please keep it in your translation, just move it to
wherever it naturally belongs in your language's sentence order. Poedit will
warn you if a translation is missing a placeholder the original has, which is
a good sign something needs a second look.

You'll also see a few strings that are proper nouns ("Orcshot" itself) or
pure symbols/numbers - those are meant to stay as-is and shouldn't need
translating at all.

## Sending it back

**If you're comfortable with GitHub:** open a pull request adding or
updating your file under `po/`. That's it - no other files need to change.

**If you're not:** that's completely fine. Just
[open an issue](https://github.com/artificialorctelligence/orcshot/issues/new)
and attach your `.po` file. If you'd rather not use GitHub at all, you can
instead email it to <orc.shot@yahoo.com>. Either way, someone will open the
pull request for you.

## What happens after that

A maintainer will look over the translation (ideally with help from another
speaker of that language, since translation quality matters and none of us
personally verify every language), merge it in, and it'll ship in the next
release.
