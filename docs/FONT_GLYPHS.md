# Font Glyph Scanning And Overrides

## Scope

The font system scans project-local font files and exposes glyph metadata for the desktop editor. It does not assume glyphs are normal Unicode letters. Unicode PUA characters and unmapped font glyphs are both surfaced.

## Scan Sources

The API scans these project locations:

- `assets/fonts`
- `BirthMonth flowers`
- `Birthmonth_font.ttf`

Supported formats:

- `.ttf`
- `.otf`
- `.ttc`
- `.otc`

Unsupported files inside scanned font folders are reported as recoverable scan issues. A bad font file does not fail the full catalog.

## Backend API

### `GET /fonts`

Returns valid scanned fonts plus recoverable issues.

```json
{
  "fonts": [
    {
      "id": "malovely-script",
      "familyName": "Malovely Script",
      "styleName": "Regular",
      "fullName": "Malovely Script Regular",
      "postscriptName": "MalovelyScript-Regular",
      "sourcePath": "BirthMonth flowers/Malovely Script.ttf",
      "format": "ttf",
      "fileSize": 105944,
      "metrics": {
        "unitsPerEm": 1000,
        "ascender": 800,
        "descender": -200,
        "lineGap": 0,
        "capHeight": null,
        "xHeight": null,
        "bbox": { "xMin": 0, "yMin": -200, "xMax": 1000, "yMax": 900 }
      },
      "glyphCount": 430,
      "mappedGlyphCount": 380,
      "puaGlyphCount": 26
    }
  ],
  "issues": [
    {
      "code": "UNSUPPORTED_FONT_FORMAT",
      "message": "Unsupported font format: BirthMonth flowers/readme.txt",
      "path": "BirthMonth flowers/readme.txt",
      "recoverable": true
    }
  ],
  "fontCount": 1
}
```

Issue codes:

- `FONT_DIRECTORY_MISSING`
- `FONT_SOURCE_NOT_DIRECTORY`
- `UNSUPPORTED_FONT_FORMAT`
- `FONT_READ_FAILED`
- `DUPLICATE_FONT`
- `DUPLICATE_FONT_ID`

### `GET /fonts/{font_id}/glyphs`

Returns all glyphs for one font. Unicode mapped glyphs include `codepoint` and `char`. Unmapped glyphs are listed with `glyphId` and `glyphName` so they are visible for future outline-based workflows.

```json
{
  "font": {},
  "glyphs": [
    {
      "glyphId": 125,
      "glyphName": "n.005",
      "codepoint": "U+E075",
      "char": "\ue075",
      "isMapped": true,
      "isPua": true,
      "advanceWidth": 700,
      "bbox": { "xMin": 0, "yMin": 0, "xMax": 620, "yMax": 760 }
    },
    {
      "glyphId": 240,
      "glyphName": "swash.unmapped",
      "codepoint": null,
      "char": null,
      "isMapped": false,
      "isPua": false,
      "advanceWidth": 640,
      "bbox": { "xMin": -20, "yMin": -40, "xMax": 680, "yMax": 780 }
    }
  ],
  "issues": [],
  "glyphCount": 2
}
```

Missing fonts return:

```json
{
  "error": {
    "code": "FONT_NOT_FOUND",
    "message": "Font was not found.",
    "details": { "fontId": "missing" },
    "recoverable": true
  }
}
```

## Frontend Behavior

`GlyphPicker` appears in the inspector when the selected layer is a text layer.

The picker:

- matches the selected layer font using `fontRef.assetId`, `fontRef.family`, and scanned font family names
- lists all glyphs, PUA glyphs, Unicode mapped glyphs, and unmapped glyphs
- allows replacement only when a glyph has a Unicode `char`
- leaves unmapped glyphs visible but disabled for replacement until outline export/editing is implemented

## Layer JSON

Glyph replacement does not mutate the text layer's original `text`.

```json
{
  "id": "layer_customer_name",
  "type": "text",
  "text": "Avery",
  "glyphOverrides": [
    {
      "index": 4,
      "originalText": "y",
      "replacement": "\ue123",
      "codepoint": "U+E123",
      "glyphName": "y.swash"
    }
  ]
}
```

`index` is a Unicode code point index, not a UTF-16 code unit index. This preserves correct behavior for supplementary-plane characters.

During editing, Fabric receives a render string rebuilt from `text + glyphOverrides`. Saved JSON keeps the original text and the override metadata.

## Limitations

- Unmapped glyphs cannot be inserted as text because they have no Unicode character. They need a later glyph-outline path workflow.
- Browser text rendering still depends on the font being available to the renderer process.
- DXF export should convert text to paths before relying on custom glyph appearance.
