#!/usr/bin/env node
/*
 * Render an HTML overlay to a TRANSPARENT PNG via headless Chrome.
 *
 * Wie render_image_post.cjs, aber mit omitBackground:true — fuer Overlays, die
 * mit Alpha ueber ein Video gelegt werden (z.B. die Sprecher-ID-Box der
 * Testimonial-Videos). Der Body muss transparenten Hintergrund haben.
 *
 * Usage:
 *   node render_transparent.cjs <html_path> <out_png> [width] [height]
 */
const path = require("path");
const fs = require("fs");
const puppeteer = require("puppeteer-core");

const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  process.env.CHROME_PATH || "",
].filter(Boolean);

function findChrome() {
  for (const c of CHROME_CANDIDATES) if (fs.existsSync(c)) return c;
  throw new Error("Kein Chrome/Chromium gefunden. CHROME_PATH setzen.");
}

(async () => {
  const [, , htmlPath, outPath, wArg, hArg] = process.argv;
  if (!htmlPath || !outPath) {
    console.error("usage: node render_transparent.cjs <html> <out.png> [w] [h]");
    process.exit(2);
  }
  const W = parseInt(wArg || "1920", 10);
  const H = parseInt(hArg || "1080", 10);

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
      omitBackground: true,
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
