"""Assembles docs/screenshots/logo-anim.gif from the frames the logo spec captures (deterministic: every CSS animation is paused and seeked to t, 50 ms apart).

    cd web && LOGO_FRAMES=../var/logo-frames npx playwright test e2e/logo.spec.ts      (needs the dev server: npm run dev)
    python scripts/make_logo_gif.py var/logo-frames"""
import glob, os, sys
from PIL import Image, ImageChops

src = sys.argv[1] if len(sys.argv) > 1 else "var/logo-frames"
ims = [Image.open(f).convert("RGB") for f in sorted(glob.glob(os.path.join(src, "f*.png")))]
bbox = ImageChops.difference(ims[-1], Image.new("RGB", ims[-1].size, ims[-1].getpixel((2, 2)))).getbbox()
x0, y0, x1, y1 = bbox; m = 28
box = (max(0, x0 - m), max(0, y0 - m), min(ims[-1].width, x1 + m), min(ims[-1].height, y1 + m))
w = 520
ims = [i.crop(box) for i in ims]
ims = [i.resize((w, round(i.height * w / i.width)), Image.LANCZOS).quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for i in ims]
out = os.path.join("docs", "screenshots", "logo-anim.gif")
ims[0].save(out, save_all=True, append_images=ims[1:], duration=[50] * (len(ims) - 1) + [2200], loop=0, optimize=True, disposal=1)
print(f"wrote {out}: {len(ims)} frames, {os.path.getsize(out) // 1024} KB")
