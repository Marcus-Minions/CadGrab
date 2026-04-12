<div align="center">

<img src="CadGrabLogo.png" alt="CadGrab Logo" width="200" height="200" />

# CadGrab FTC

**The Ultimate Automated CAD Scraper & Fusion 360 Importer for FIRST Tech Challenge**

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Fusion 360 Add-In](https://img.shields.io/badge/Autodesk-Fusion_360-orange.svg?logo=autodesk&logoColor=white)](https://www.autodesk.com/products/fusion-360)
[![Supported](https://img.shields.io/badge/Sites-goBILDA%20%7C%20REV%20%7C%20AndyMark-success.svg)](#)

*Developed by **Krshs90**, a contributor to the **[Marcus Minions #22077](https://github.com/Marcus-Minions)***.  
*Bug fixed by **Google Antigravity** & Documentation by **Gemini 3.1 Pro**.*

[Download Pre-Scraped ZIP (All Vendors)](https://drive.google.com/file/d/1qAPvSF52KXlNo_g6LzP66fs2j6ajIA6k/view?usp=sharing) • [Report Bug](https://github.com/Marcus-Minions/CadGrab-FTC/issues) • [Request Feature](https://github.com/Marcus-Minions/CadGrab-FTC/issues)

</div>

---

## 📖 Overview

**CadGrab** is a powerful, automated Python scraper and download manager designed to extract, organize, and rename 3D CAD (`.step`) files from the most popular FIRST Tech Challenge (FTC) robotics vendors.

### Supported Vendors:
1. 🟠 **goBILDA**
2. 🟣 **REV Robotics**
3. 🔵 **AndyMark** *(Beta)*

Unlike standard web scrapers, vendors often hide their product variations (like lengths of U-Channel or motor gear ratios) inside Javascript rendering engines, making them invisible to regular crawling. **CadGrab** solves this by using a hybrid engine: it parses raw XML sitemaps to discover base products, then completely bypasses JS obfuscation using a **Universal Multithreaded Regex Spider** to rip every valid product URL directly from the hidden HTML map.

---

## ✨ Features

- ⚡️ **Multi-Site Architecture:** One script to rule them all. Scrape all 3 major vendors at once, or select just one via the interactive CLI prompt.
- 📂 **Smart Directory Organization:** Programmatically reads website breadcrumbs to automatically build a perfectly categorized folder directory merging all vendors seamlessly (e.g., `CAD_Files/MOTION/Motors`).
- 🛡️ **Path Sanitization:** Automatically truncates folder paths and wipes invalid Windows characters (like `3/16"`) to prevent OS-level path crashes and respect `MAX_PATH` limits.
- 🏷️ **Intelligent Auto-Renaming:** Standardizes and intelligently shortens file names. Say goodbye to long "Series" prefixes and trademark symbols. Your Fusion 360 library will look pristine.
- ⏭️ **Smart Duplicate Skipping:** Stop the script halfway? No problem. It memorizes what it has collected and instantly skips pre-downloaded files upon restart to save massive bandwidth.

---

## 🚀 Getting Started

### Prerequisites

Ensure you have **Python 3.8+** installed on your machine.

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/Marcus-Minions/CadGrab-FTC.git
   cd CadGrab-FTC
   ```
2. Install the required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Running the Scraper

1. Open a terminal in the project directory.
2. Run the script:
   ```bash
   python cad_grab.py
   ```
3. An interactive prompt will appear:
   ```text
   Select websites to scrape CAD parts from:
   [1] goBILDA
   [2] REV Robotics
   [3] AndyMark
   [4] ALL of the above
   
   Enter choice (1-4):
   ```
4. **Sit back and relax.** The script will create a root `CAD_Files` directory and begin placing thousands of `.step` files perfectly into categorized sub-folders!

> **💡 Pro Tip:** Change `DRY_RUN = True` inside `cad_grab.py` if you simply want to scan the sites and preview the file output paths without utilizing network data.

---

## 🛠 Fusion 360 Integration

If you want to quickly bulk import all of these downloaded `.step` files while completely preserving their exact folder categories inside your Autodesk Fusion 360 Data Panel, this repository includes our custom **CadGrab Fusion 360 Add-In**!

1. Open Fusion 360 and navigate to the **Design** workspace.
2. Select **Utilities** > **Scripts and Add-Ins** (or press `Shift + S`).
3. Under the **Scripts** tab, click the green `+` icon next to **My Scripts**.
4. Select the `FusionScript` folder located inside your cloned `CadGrab-FTC` directory.
5. Click **Run** on the `CadGrab_Fusion_Import` script!
6. A dialog will prompt you to select the exact `CAD_Files` folder that the scraper built.
7. Select exactly which categories to upload (e.g., "Check *Motion*", "Uncheck *Hardware*").
8. Fusion will now replicate the folders perfectly into your cloud Project!

> **⚠️ Note:** This process can take a significant amount of time depending on the number of files and your internet upload speed. Importing the *entire* goBILDA library takes approximately 3 hours. If you cancel it, running it again will instantaneously skip duplicates thanks to the Add-In's memory cache!

---

## 🔌 Headless API (For Developers)

CadGrab-FTC includes a fully headless background scraper built directly into the Fusion 360 Add-In that operates without triggering any UI. This allows other Fusion 360 Add-Ins (like drive-base generators) to dynamically request components on the fly without breaking the user experience.

If your Add-In needs a part, you can simply fire CadGrab's custom listener from anywhere in Fusion Python:

```python
import json

# Request a specific item to be seamlessly dropped into the active viewport
payload = {
    "supplier": "goBILDA", 
    "part_number": "3110-0016-0001"
}
app.fireCustomEvent('CadGrab_FetchPart_Event', json.dumps(payload))
```

This invokes the hyper-fast internal spider that bypasses the need for the `requests` library. It locates the `.step` file on the remote server, unpacks the zip internally, automatically caches it locally inside your Temp directory for instant repeat usage, and drops it into the active root component as an occurrence!

*If you need to stall your script until the part arrives, CadGrab responds with `CadGrab_FetchPart_Success_Event` when finished.*

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
