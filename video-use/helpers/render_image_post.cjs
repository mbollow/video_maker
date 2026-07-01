#!/usr/bin/env node
/*
 * Render a single still HTML composition to PNG via headless Chrome.
 *
 * Used by the Bild-Post pipeline (Phase 2 "bild:build"): a static-post.html is
 * filled with the chosen photo + hook/spruch text, then captured here as one
 * frame — no video, just a 1080x1350 (4:5) still by default.
 *
 * Usage:
 *   node render_image_post.js <html_path> <out_png> [width] [height]
 *
 * Resolves puppeteer-core + the locally installed Chrome. Waits for fonts and
 * images to settle before the screenshot so Google-Fonts (Montserrat) and the
 * photo are fully painted.
 */
const path = require("path");
const puppeteer = require("puppeteer-core");

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  process.env.CHROME_PATH || "",
].filter(Boolean);

const fs = require("fs");
function findChrome() {
  for (const c of CHROME_CANDIDATES) if (fs.existsSync(c)) return c;
  throw new Error("Kein Chrome/Chromium gefunden. CHROME_PATH setzen.");
}

(async () => {
  const [, , htmlPath, outPath, wArg, hArg] = process.argv;
  if (!htmlPath || !outPath) {
    console.error("usage: node render_image_post.js <html> <out.png> [w] [h]");
    process.exit(2);
  }
  const W = parseInt(wArg || "1080", 10);
  const H = parseInt(hArg || "1350", 10);

  const browser = await puppeteer.launch({
    executablePath: findChrome(),
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1"],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
    const url = "file://" + path.resolve(htmlPath);
    await page.goto(url, { waitUntil: "load", timeout: 60000 });
    // Fonts + images fully settled
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) await document.fonts.ready;
      const imgs = Array.from(document.images);
      await Promise.all(
        imgs.map((img) =>
          img.complete
            ? Promise.resolve()
            : new Promise((res) => {
                img.onload = img.onerror = res;
              })
        )
      );
    });
    await new Promise((r) => setTimeout(r, 250));
    await page.screenshot({
      path: outPath,
      clip: { x: 0, y: 0, width: W, height: H },
    });
    console.log("rendered:", outPath, `${W}x${H}`);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
