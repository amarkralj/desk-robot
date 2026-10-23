# DeskBot content library

The `en.json` and `de.json` files use schema version 1. They are local,
version-controlled dialogue data. Loading a file only parses and validates
it; it never selects, speaks, or performs a response.

Each file is a JSON object with:

- `schema_version`: integer `1`.
- `language`: the file's language, exactly `en` or `de`.
- Non-empty response arrays named `greet_known`, `greet_unknown`, `head_tap`,
  `sneeze`, `joke_offer`, `boss_absent`, `boss_present`, and `idle_reaction`.
- `joke_answer`: an object with exactly `yes` and `no` arrays. The `yes`
  array contains the original local jokes; the `no` array contains playful,
  respectful declines.

Every entry has:

- `id`: stable, unique within the language file, lowercase letters/digits
  followed by optional lowercase letters, digits, `_`, or `-` (up to 64
  characters). Keep corresponding English and German IDs identical.
- `text`: non-empty dialogue. `greet_known` entries must include
  `{person_name}`; callers supply a first name at response time. Do not put
  actual personal names or other personal data in these files.
- `expression`: one of the existing firmware expressions: `neutral`,
  `happy`, `sad`, `angry`, `surprised`, `sleepy`, `thinking`, `curious`,
  `skeptical`, `excited`, `love`, or `confused`.
- `action`: `null` (no action), or one of `blink`, `nod`, `head_tilt`,
  `sneeze_animation`, `laugh`.
- `fallback`: boolean. Exactly one entry in each response array must be
  `true`. Normal selection prefers non-fallback entries; the fallback is
  selected when it is the only entry left in that array.

To add dialogue, add an entry with a new stable ID. To remove dialogue,
remove its entry, but retain one fallback in every array. Both languages
are validated independently before use. Missing files, malformed JSON,
invalid schema, or absent fallbacks produce an explicit non-spoken
`content_unavailable` response; the code does not substitute hosted dialogue
or an LLM response.

The German file may also contain an `owner_greetings` list. It uses the same
entry structure, requires at least four unique entries, and every phrase must
address the explicitly configured owner as `Chef`. Owner greeting selection
avoids the last three response IDs and never falls back to generated dialogue.

The dialogue is original and written for this project. Keep it playful and
kind: sarcasm should be self-deprecating or directed at the situation, never
hostile toward colleagues or visitors.
