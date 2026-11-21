import { describe, expect, it } from "vitest";
import { wikimediaFilePageUrl } from "./wikimediaCredit";

describe("wikimediaFilePageUrl", () => {
  it("turns a Commons thumbnail URL into the file's page, decoded once", () => {
    expect(
      wikimediaFilePageUrl(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/BMW_G20_LCI_320i_Alpine_White_%281%29.jpg/1280px-BMW_G20_LCI_320i_Alpine_White_%281%29.jpg",
      ),
    ).toBe("https://commons.wikimedia.org/wiki/File:BMW_G20_LCI_320i_Alpine_White_(1).jpg");
  });

  it("does the same for the thumbnail host the Commons API returns today", () => {
    expect(
      wikimediaFilePageUrl(
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/07/2022_Porsche_Macan_IMG_6376.jpg/1280px-2022_Porsche_Macan_IMG_6376.jpg",
      ),
    ).toBe("https://commons.wikimedia.org/wiki/File:2022_Porsche_Macan_IMG_6376.jpg");
  });

  it("turns an original-size Commons URL into the file's page", () => {
    expect(wikimediaFilePageUrl("https://upload.wikimedia.org/wikipedia/commons/7/7d/Porsche_Macan_4_DSC_6050.jpg")).toBe(
      "https://commons.wikimedia.org/wiki/File:Porsche_Macan_4_DSC_6050.jpg",
    );
  });

  it("decodes a non-ASCII file name once", () => {
    expect(
      wikimediaFilePageUrl("https://upload.wikimedia.org/wikipedia/commons/2/23/Volvo_XC90_%E2%80%93_f_03102025.jpg"),
    ).toBe("https://commons.wikimedia.org/wiki/File:Volvo_XC90_–_f_03102025.jpg");
  });

  it.each([
    "https://example.test/alphard.jpg",
    "https://evil.example/wikipedia/commons/2/2f/BMW.jpg",
    "http://upload.wikimedia.org/wikipedia/commons/2/2f/BMW.jpg",
    "https://upload.wikimedia.org/wikipedia/en/2/2f/BMW.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/2/2f/",
    "not a url",
    "",
    null,
    undefined,
  ])("gives null for %j (no credit line)", (url) => {
    expect(wikimediaFilePageUrl(url)).toBeNull();
  });
});
