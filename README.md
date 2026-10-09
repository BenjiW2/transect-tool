# Transect tool

Turns a series of overhead photos taken along a transect tape into one long, straight image of the
transect, and marks every segment from the benthic data sheet on it (boundary lines, cm values, and a
coloured category bar).

The image is built from the **tape itself**: you read a few numbers off the tape in each photo, and the
tool places every photo so that 1 cm of tape is always the same number of pixels. That makes the markers
land in the right place even when the camera height and tilt change, or the tape twists over to its
feet/inches side.

## Getting it

### Mac app (easiest, nothing else to install)

Download `Transect-Tool-<version>-mac.dmg` from the
[Releases page](../../releases). Open it and drag **Transect Tool** into Applications.

The first time you open it, macOS blocks it because the app isn't from the App Store. Click **Done**, then
go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. You only need to do
this once.

Needs a Mac with Apple silicon (M1 or newer) on macOS 13 Ventura or later. Your transects are saved in
`Documents/Transect Tool`.

### Windows app (nothing else to install)

From the [Releases page](../../releases), download either:

* `Transect-Tool-<version>-windows-setup.exe`: an installer. It adds Transect Tool to the Start menu and
  doesn't need admin rights.
* `Transect-Tool-<version>-windows-portable.zip`: no install. Unzip it anywhere and run `Transect Tool.exe`.

Windows may show "Windows protected your PC" because the app isn't signed. Click **More info → Run
anyway**. Needs 64-bit Windows 10 or 11. It uses Microsoft Edge's WebView2, which comes with Windows 11
and up-to-date Windows 10. If WebView2 is missing, the tool opens in your normal web browser instead.
Transects are saved in `Documents\Transect Tool`, and the log is in `%LOCALAPPDATA%\Transect Tool`.

### From source (Mac or Windows, needs Python 3.9+)

* **Mac:** double-click `Start Transect Tool.command`.
* **Windows:** double-click `Start Transect Tool (Windows).bat`.

The first start installs what it needs (a minute or two, needs internet). A browser page then opens at
<http://127.0.0.1:8765>. Keep the terminal window open while you use the tool. Close it to stop.
Transects are saved in the `projects` folder next to the code.

Everything runs on your own computer. Nothing is uploaded to the internet.

## Using it

1. **New transect.** Give it a name, then drag in all the photos and the data sheet CSV, and click
   Upload. The tool finds the tape in each photo as they upload.
2. **Photos & data sheet.** Untick anything that isn't a transect photo (e.g. photos of the slate).
   Check that the data sheet was read (it shows the number of segments and the cm range).
   Photos are used in file-name order.
3. **Read the tape.** For each photo you see a straightened strip along the tape.
   * Click **exactly on the tick mark** of a number you can read and type its value. Press Enter.
   * Add **at least 2 readings per photo, ideally 3–5 spread from left to right.**
   * What to type is the full distance along the tape:
     * Metric side: `760`, `760cm` or `7.6m`. The black 10…90 are tens of cm within the current metre,
       so the "60" after the red "7 m" is `760`. The red "7 m" itself is `7m`.
     * Feet/inches side (tape flipped over): the red "N FT" is whole feet and the black 1–11 are inches.
       Type `12ft 7in` or `12'7`. It's converted to cm for you.
   * The page shows which cm range the neighbouring photos cover, to help you get the metre right.
   * **Fix tape line:** if the strip doesn't show the tape, click this and click two points on the tape
     in the photo.
   * **Skip photo:** if the tape can't be read at all (e.g. twisted edge-on). That's fine as long as the
     photos either side overlap. The build tells you if it leaves a gap.
   * Status colours: **ok**, **check** (readings in the photo disagree, or don't follow on from the
     neighbours, usually a wrong metre or a typo), **todo** (fewer than 2 readings).
   * Use the ← / → keys to move between photos.
4. **Build image.** Click Build (about a minute). Save or download:
   * `…_marked.jpg`: the transect with all markers,
   * `…_clean.jpg`: the same image without markers,
   * `…_tape_readings.csv`: every reading and how well it fits, for your records.

Your work is saved as you go. Reopen a transect from the start page to continue later.

## Data sheet format

A CSV with a header row. The tool looks for these columns by name: `Transect measurement start (cm)`,
`Transect measurement finish (cm)`, `Major`, `Minor` (plus `Site`, `Date`, `Time`, `Depth`,
`Compass bearing`, `Transect group number` for the title). Rows without a start value are treated as
extra categories of the segment above (e.g. "Mixed" entries). Rows where start = finish (start/end
rows) are ignored.

## Notes

* **Output size:** at the default 20 px per cm, a 20 m transect is about 40,000 px wide. Very long
  transects are scaled down automatically to stay within the JPEG size limit.
* **Accuracy:** markers are as accurate as the readings, typically within 1–2 cm. Things that stand well
  above the bottom (tall coral heads) can look slightly doubled where photos overlap, because they're
  seen from different angles.
* **Where things are kept:** each project (photos, readings and outputs) is a folder in
  `Documents/Transect Tool` (Mac app) or `projects` (from source). Delete a project's folder to remove it.
* **Problems with the Mac app:** there's a log at `~/Library/Logs/Transect Tool.log`.

## Building the apps

### Windows

Built automatically on GitHub (`.github/workflows/windows.yml`) whenever a version tag such as `v1.2.0`
is pushed. The installer and portable zip are attached to that release. You can also run it by hand from
the Actions tab. Each build runs a self-test of the packaged app (`Transect Tool.exe --selftest`).

### Mac

Needs [uv](https://docs.astral.sh/uv/) on an Apple-silicon Mac:

```
packaging/build_mac.sh
```

This produces `dist/Transect-Tool-<version>-mac.dmg`. The version number is in `packaging/VERSION`.
The script downloads its own Python and picks libraries that run on macOS 13+, so the result doesn't
depend on what's installed on the build machine. The app is ad-hoc signed only. To make it open without
the "Open Anyway" step, sign and notarise it with an Apple Developer ID.

## Code layout

* `pipeline.py`: image processing (tape detection, fitting readings, rendering the strip, drawing markers)
* `app.py`: the local web server and project storage
* `static/`: the web page
* `desktop.py`: Mac app entry point (native window around the web page)
* `packaging/`: app icon, PyInstaller spec, build script
