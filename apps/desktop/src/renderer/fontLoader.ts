import type { FontSummary } from "./api/client";

export async function loadProjectFonts(
  fonts: readonly FontSummary[],
  fontFileUrl: (fontId: string) => string,
): Promise<number> {
  if (
    typeof window === "undefined" ||
    typeof FontFace === "undefined" ||
    !("fonts" in window.document)
  ) {
    return 0;
  }

  let loaded = 0;
  for (const font of fonts) {
    const family = font.familyName.trim();
    if (!family) {
      continue;
    }

    try {
      const face = new FontFace(family, `url("${fontFileUrl(font.id)}")`);
      const loadedFace = await face.load();
      window.document.fonts.add(loadedFace);
      loaded += 1;
    } catch {
      // 字体文件可能损坏或被占用；目录扫描会继续暴露问题，画布不应因此整体崩溃。
    }
  }

  if (loaded > 0) {
    await window.document.fonts.ready;
  }

  return loaded;
}
