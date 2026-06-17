import { describe, expect, it } from "vitest";

import { ADD_ASSET_BUTTON_LABEL } from "./editorLabels";

describe("editor labels", () => {
  it("uses the product term 素材 for the asset add button", () => {
    expect(ADD_ASSET_BUTTON_LABEL).toBe("添加素材");
  });
});
