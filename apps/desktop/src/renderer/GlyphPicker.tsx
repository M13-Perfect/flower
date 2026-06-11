import { useEffect, useMemo, useState } from "react";

import type { TextLayer } from "@flower/design-core";
import type { ApiClient, FontSummary, GlyphInfo } from "./api/client";
import type { TextGlyphOverrideInput } from "./canvas/layerFabricModel";

type LoadState<T> =
  | { status: "idle" | "loading" }
  | { status: "ready"; value: T }
  | { status: "error"; message: string };

interface GlyphPickerProps {
  apiClient: ApiClient;
  layer: TextLayer | null;
  onApplyGlyph: (input: TextGlyphOverrideInput) => void;
}

type GlyphFilter = "all" | "pua" | "mapped" | "unmapped";

export function GlyphPicker({ apiClient, layer, onApplyGlyph }: GlyphPickerProps) {
  const [fontsState, setFontsState] = useState<LoadState<FontSummary[]>>({ status: "loading" });
  const [selectedFontId, setSelectedFontId] = useState("");
  const [glyphsState, setGlyphsState] = useState<LoadState<GlyphInfo[]>>({ status: "idle" });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [filter, setFilter] = useState<GlyphFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setFontsState({ status: "loading" });

    apiClient
      .listFonts()
      .then((response) => {
        if (!cancelled) {
          setFontsState({ status: "ready", value: response.fonts });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setFontsState({
            status: "error",
            message: error instanceof Error ? error.message : "Font scan failed",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [apiClient]);

  const fonts = fontsState.status === "ready" ? fontsState.value : [];
  const textChars = useMemo(() => Array.from(layer?.text ?? ""), [layer?.text]);
  const matchedFontId = useMemo(() => (layer ? matchLayerFont(layer, fonts)?.id ?? "" : ""), [fonts, layer]);

  useEffect(() => {
    setSelectedFontId(matchedFontId || fonts[0]?.id || "");
  }, [fonts, matchedFontId, layer?.id]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [layer?.id]);

  useEffect(() => {
    if (!selectedFontId) {
      setGlyphsState({ status: "idle" });
      return;
    }

    let cancelled = false;
    setGlyphsState({ status: "loading" });

    apiClient
      .listFontGlyphs(selectedFontId)
      .then((response) => {
        if (!cancelled) {
          setGlyphsState({ status: "ready", value: response.glyphs });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setGlyphsState({
            status: "error",
            message: error instanceof Error ? error.message : "Glyph scan failed",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [apiClient, selectedFontId]);

  const glyphs = glyphsState.status === "ready" ? glyphsState.value : [];
  const visibleGlyphs = glyphs.filter((glyph) => {
    if (filter === "pua") {
      return glyph.isPua;
    }
    if (filter === "mapped") {
      return glyph.isMapped;
    }
    if (filter === "unmapped") {
      return !glyph.isMapped;
    }
    return true;
  });

  const canApply = layer !== null && textChars.length > 0;

  return (
    <section className="glyph-panel" aria-label="Glyph picker">
      <div className="panel-header">
        <h2>Glyphs</h2>
        <span>{layer?.type === "text" ? layer.fontRef.family : "text only"}</span>
      </div>

      {!layer ? <p className="empty-state">No text layer selected.</p> : null}

      {layer ? (
        <>
          <label className="select-field">
            <span>font</span>
            <select
              disabled={fontsState.status !== "ready" || fonts.length === 0}
              onChange={(event) => setSelectedFontId(event.currentTarget.value)}
              value={selectedFontId}
            >
              {fonts.map((font) => (
                <option key={font.id} value={font.id}>
                  {font.familyName}
                </option>
              ))}
            </select>
          </label>

          {fontsState.status === "error" ? <p className="inline-error">{fontsState.message}</p> : null}
          {fontsState.status === "ready" && fonts.length === 0 ? (
            <p className="empty-state">No project fonts found.</p>
          ) : null}
          {fontsState.status === "ready" && matchedFontId === "" && fonts.length > 0 ? (
            <p className="inline-warning">Current font not found.</p>
          ) : null}

          <label className="select-field">
            <span>char</span>
            <select
              disabled={textChars.length === 0}
              onChange={(event) => setSelectedIndex(Number(event.currentTarget.value))}
              value={Math.min(selectedIndex, Math.max(0, textChars.length - 1))}
            >
              {textChars.map((char, index) => (
                <option key={`${char}-${index}`} value={index}>
                  {index}: {char}
                </option>
              ))}
            </select>
          </label>

          <div className="segmented-control" aria-label="Glyph filter">
            {(["all", "pua", "mapped", "unmapped"] as const).map((value) => (
              <button
                className={filter === value ? "active" : ""}
                key={value}
                onClick={() => setFilter(value)}
                type="button"
              >
                {value}
              </button>
            ))}
          </div>

          {glyphsState.status === "loading" ? <p className="empty-state">Loading glyphs.</p> : null}
          {glyphsState.status === "error" ? <p className="inline-error">{glyphsState.message}</p> : null}

          <div className="glyph-grid" aria-label="Available glyphs">
            {visibleGlyphs.slice(0, 240).map((glyph) => (
              <button
                className={glyph.isPua ? "glyph-cell pua" : "glyph-cell"}
                disabled={!canApply || !glyph.char}
                key={`${glyph.glyphName}-${glyph.codepoint ?? glyph.glyphId}`}
                onClick={() => {
                  if (!glyph.char) {
                    return;
                  }
                  onApplyGlyph({
                    index: selectedIndex,
                    replacement: glyph.char,
                    codepoint: glyph.codepoint ?? undefined,
                    glyphName: glyph.glyphName,
                  });
                }}
                title={`${glyph.glyphName}${glyph.codepoint ? ` ${glyph.codepoint}` : ""}`}
                type="button"
              >
                <span className="glyph-preview">{glyph.char ?? "gid"}</span>
                <span className="glyph-name">{glyph.glyphName}</span>
                <span className="glyph-code">{glyph.codepoint ?? `#${glyph.glyphId}`}</span>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function matchLayerFont(layer: TextLayer, fonts: readonly FontSummary[]): FontSummary | null {
  const candidates = [
    layer.fontRef.assetId,
    slug(layer.fontRef.family),
    layer.fontRef.family.trim().toLocaleLowerCase(),
  ].filter((value): value is string => typeof value === "string" && value.length > 0);
  const normalizedFamily = layer.fontRef.family.trim().toLocaleLowerCase();

  return (
    fonts.find(
      (font) =>
        candidates.includes(font.id) ||
        font.familyName.trim().toLocaleLowerCase() === normalizedFamily ||
        font.fullName.trim().toLocaleLowerCase() === normalizedFamily,
    ) ?? null
  );
}

function slug(value: string): string {
  return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
