import requests
from bs4 import BeautifulSoup
import os
import re
import zipfile
import tempfile
import time
import sys
import json
import xml.etree.ElementTree as ET
import concurrent.futures
from urllib.parse import urljoin
from typing import Set, List, Tuple, Optional, Dict, Any

# Fix Windows console encoding issues with special characters
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8') # type: ignore
    except AttributeError:
        pass

DOWNLOAD_DIR = "CAD_Files"
DRY_RUN = False
LINK_ONLY_MODE = True
LINK_MANIFEST_NAME = "cad_links_manifest.json"
LINK_MANIFEST_PATH = os.path.join(DOWNLOAD_DIR, LINK_MANIFEST_NAME)
REQUIRED_LINK_MANIFEST_FIELDS = ("url", "product_url", "vendor")
_link_manifest: Dict[str, Dict[str, Any]] = {}

STANDARD_CATEGORIES = {
    "electronics": "ELECTRONICS",
    "hardware": "HARDWARE",
    "kits": "KITS",
    "motion": "MOTION",
    "structure": "STRUCTURE",
    "ftc": "STRUCTURE", 
    "mechanical": "MOTION",
}

def clean_filename(name: str) -> str:
    name = re.sub(r'\d{4} Series\s*', '', name)
    name = re.sub(r'goBILDA®?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'REV Robotics', '', name, flags=re.IGNORECASE)
    name = re.sub(r'AndyMark', '', name, flags=re.IGNORECASE)
    name = name.replace('™', '').replace('®', '').replace('©', '')
    name = name.replace('(', '').replace(')', '').replace(',', '')
    name = name.replace(':', ' ')
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip()

KEYWORD_CATEGORIES = {
    "motor controller": ["ELECTRONICS", "Controllers"], "servo controller": ["ELECTRONICS", "Controllers"], "spark": ["ELECTRONICS", "Controllers"],
    "sensor": ["ELECTRONICS", "Sensors"], "cable": ["ELECTRONICS", "Cables"], "wire": ["ELECTRONICS", "Cables"], "battery": ["ELECTRONICS", "Power"],
    "power": ["ELECTRONICS", "Power"], "switch": ["ELECTRONICS", "Power"], "control hub": ["ELECTRONICS", "Control Systems"],
    "expansion hub": ["ELECTRONICS", "Control Systems"], "camera": ["ELECTRONICS", "Vision"], "vision": ["ELECTRONICS", "Vision"], "logic level": ["ELECTRONICS", "Sensors"],
    "encoder": ["ELECTRONICS", "Sensors"], "board": ["ELECTRONICS", "Boards"], "limelight": ["ELECTRONICS", "Vision"], "roborio": ["ELECTRONICS", "Control Systems"],
    "memory card": ["ELECTRONICS", "Storage"], "regulator": ["ELECTRONICS", "Power"], "bec": ["ELECTRONICS", "Power"], "led light": ["ELECTRONICS", "Lighting"],
    "lidar": ["ELECTRONICS", "Sensors"], "signal light": ["ELECTRONICS", "Lighting"], "slip ring": ["ELECTRONICS", "Misc"], "meter": ["ELECTRONICS", "Misc"],
    "motor": ["MOTION", "Motors"], "servo": ["MOTION", "Servos"], "wheel": ["MOTION", "Wheels"], "gear": ["MOTION", "Gears"], "sprocket": ["MOTION", "Sprockets"],
    "pulley": ["MOTION", "Pulleys"], "belt": ["MOTION", "Belts"], "chain": ["MOTION", "Chain"], "bearing": ["MOTION", "Bearings"], "shaft": ["MOTION", "Shafting"],
    "axle": ["MOTION", "Shafting"], "hub": ["MOTION", "Hubs"], "mecanum": ["MOTION", "Wheels"], "omni": ["MOTION", "Wheels"], "caster": ["MOTION", "Wheels"],
    "pinion": ["MOTION", "Gears"], "gearbox": ["MOTION", "Gearboxes"], "linear": ["MOTION", "Linear Motion"], "lead screw": ["MOTION", "Linear Motion"],
    "tire": ["MOTION", "Wheels"], "coupler": ["MOTION", "Couplers"], "worm": ["MOTION", "Gears"], "slider": ["MOTION", "Linear Motion"], "pillow block": ["MOTION", "Bearings"],
    "drive": ["MOTION", "Chassis"], "turntable": ["MOTION", "Turntables"], "spool": ["MOTION", "Spools"], "tensioner": ["MOTION", "Chain"], "track": ["MOTION", "Tracks"],
    "robits": ["MOTION", "Kits"], "strafer": ["MOTION", "Chassis"],
    "channel": ["STRUCTURE", "Channel"], "extrusion": ["STRUCTURE", "Extrusion"], "tube": ["STRUCTURE", "Tubing"], "plate": ["STRUCTURE", "Plates"],
    "bracket": ["STRUCTURE", "Brackets"], "mount": ["STRUCTURE", "Mounts"], "beam": ["STRUCTURE", "Beams"], "rail": ["STRUCTURE", "Rails"],
    "standoff": ["STRUCTURE", "Standoffs"], "spacer": ["STRUCTURE", "Spacers"], "gusset": ["STRUCTURE", "Gussets"], "spline": ["STRUCTURE", "Splines"],
    "sheet": ["STRUCTURE", "Materials"], "polycarbonate": ["STRUCTURE", "Materials"], "rod": ["STRUCTURE", "Tubing"], "churro": ["STRUCTURE", "Tubing"],
    "disk": ["STRUCTURE", "Plates"], "chassis": ["STRUCTURE", "Chassis"], "box": ["STRUCTURE", "Enclosures"], "enclosure": ["STRUCTURE", "Enclosures"],
    "frame": ["STRUCTURE", "Frames"], "pipe": ["STRUCTURE", "Tubing"], "tray": ["STRUCTURE", "Misc"], "table": ["STRUCTURE", "Misc"],
    "panel": ["STRUCTURE", "Panels"], "perimeter": ["STRUCTURE", "Misc"], "support": ["STRUCTURE", "Brackets"], "container": ["STRUCTURE", "Misc"],
    "brace": ["STRUCTURE", "Brackets"], "upright": ["STRUCTURE", "Brackets"],
    "screw": ["HARDWARE", "Screws"], "nut": ["HARDWARE", "Nuts"], "bolt": ["HARDWARE", "Screws"], "washer": ["HARDWARE", "Washers"],
    "collar": ["HARDWARE", "Collars"], "zip tie": ["HARDWARE", "Misc"], "fastener": ["HARDWARE", "Misc"], "spring": ["HARDWARE", "Springs"],
    "bungee": ["HARDWARE", "Springs"], "surgical tubing": ["HARDWARE", "Tubing"], "insert": ["HARDWARE", "Misc"], "shim": ["HARDWARE", "Spacers"],
    "adapter": ["HARDWARE", "Adapters"], "bushing": ["HARDWARE", "Bearings"], "retaining ring": ["HARDWARE", "Rings"], "tee": ["HARDWARE", "Pipe Fittings"],
    "elbow": ["HARDWARE", "Pipe Fittings"], "valve": ["HARDWARE", "Pneumatics"], "manifold": ["HARDWARE", "Pneumatics"], "air cylinder": ["HARDWARE", "Pneumatics"],
    "compressor": ["HARDWARE", "Pneumatics"], "latch": ["HARDWARE", "Misc"], "block": ["HARDWARE", "Misc"], "nubs": ["HARDWARE", "Misc"],
    "ring": ["HARDWARE", "Rings"], "pneumatic": ["HARDWARE", "Pneumatics"], "solenoid": ["HARDWARE", "Pneumatics"], "strap": ["HARDWARE", "Misc"],
    "cam follower": ["HARDWARE", "Bearings"], "hardware": ["HARDWARE", "Misc"], "hardware kit": ["HARDWARE", "Kits"],
    "kit": ["KITS", "Misc"]
}

def guess_category_from_name(name: str) -> List[str]:
    lower_name = name.lower()
    for kw, cat_list in KEYWORD_CATEGORIES.items():
        if kw in lower_name:
            return cat_list
    return ["UNCATEGORIZED"]

def normalize_category(cat: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', " ", cat).strip()
    cleaned = re.sub(r'\s+', " ", cleaned)
    lower_cat = cleaned.lower()
    for key, val in STANDARD_CATEGORIES.items():
        if key in lower_cat:
            return val
    return cleaned.upper() if cleaned else "UNCATEGORIZED"

def download_cad_file(file_url: str, target_folder: str, clean_name: str) -> None:
    try:
        response = requests.get(file_url, stream=True, timeout=15)
        response.raise_for_status()
        
        dest_path = os.path.join(target_folder, f"{clean_name}.step")
        
        # Check if it's a zip by url or content type
        is_zip = file_url.lower().endswith('.zip') or 'zip' in response.headers.get('Content-Type', '').lower()
        
        if is_zip:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip', mode='wb') as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk) # type: ignore
                tmp_path = tmp.name
                
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                step_files = [f for f in zip_ref.namelist() if f.lower().endswith('.step') or f.lower().endswith('.stp')]
                if step_files:
                    step_file_in_zip = step_files[0]
                    source = zip_ref.open(step_file_in_zip)
                    with open(dest_path, "wb") as target:
                        target.write(source.read())
                    source.close()
                    print(f"     Successfully extracted and saved: {dest_path}")
                else:
                     print(f"     No .step file found in downloaded zip for {clean_name}")
            os.remove(tmp_path)
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.step', mode='wb') as tmp:
                for chunk in response.iter_content(chunk_size=8192):
                    tmp.write(chunk) # type: ignore
                tmp_path = tmp.name
            import shutil
            shutil.move(tmp_path, dest_path)
            print(f"     Successfully saved: {dest_path}")
            
    except Exception as e:
        print(f"     Failed to download CAD {clean_name}: {e}")


def load_link_manifest() -> None:
    global _link_manifest
    if os.path.exists(LINK_MANIFEST_PATH):
        try:
            with open(LINK_MANIFEST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                validated_manifest: Dict[str, Dict[str, Any]] = {}
                for k, v in data.items():
                    if not isinstance(k, str) or not isinstance(v, dict):
                        continue
                    if not all(key in v for key in REQUIRED_LINK_MANIFEST_FIELDS):
                        continue
                    if not all(isinstance(v[key], str) and v[key] for key in REQUIRED_LINK_MANIFEST_FIELDS):
                        continue
                    validated_manifest[k] = v
                _link_manifest = validated_manifest
            else:
                _link_manifest = {}
                print(f"[WARN] Link manifest format invalid. Starting fresh: {LINK_MANIFEST_PATH}")
        except (json.JSONDecodeError, OSError) as e:
            _link_manifest = {}
            print(f"[WARN] Could not load link manifest ({e}). Starting fresh: {LINK_MANIFEST_PATH}")
    else:
        _link_manifest = {}


def save_link_manifest() -> None:
    try:
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        with open(LINK_MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(_link_manifest, f, indent=2, ensure_ascii=False, sort_keys=True)
    except OSError as e:
        print(f"[WARN] Could not save link manifest ({e}): {LINK_MANIFEST_PATH}")


def store_cad_link(file_url: str, target_folder: str, clean_name: str, product_url: str, vendor: str) -> bool:
    relative_dir = os.path.relpath(target_folder, DOWNLOAD_DIR)
    if relative_dir in (".", ""):
        relative_path = f"{clean_name}.step"
    else:
        relative_path = f"{relative_dir}/{clean_name}.step".replace("\\", "/")

    if relative_path in _link_manifest:
        return False

    _link_manifest[relative_path] = {
        "url": file_url,
        "product_url": product_url,
        "vendor": vendor
    }
    return True


def get_run_action_label() -> str:
    return 'DRY-RUN' if DRY_RUN else ('LINKING' if LINK_ONLY_MODE else 'DOWNLOADING')


def handle_link_only_entry(step_link: Optional[str], folder_path: str, clean_name: str, product_url: str, vendor_name: str) -> None:
    if step_link:
        if not store_cad_link(step_link, folder_path, clean_name, product_url, vendor_name):
            print(f"[SKIPPED] {clean_name} already exists in link manifest.")
    else:
        print(f"[SKIPPED] No STEP link found for {clean_name}.")


class BaseScraper:
    name: str = "Base"
    base_url: str = ""
    
    def run(self):
        print(f"\n--- Starting {self.name} Scraper ---")
        urls = list(self.get_all_product_urls())
        
        urls_to_process = urls[:50] if DRY_RUN else urls # type: ignore
        print(f"\nFound {len(urls)} total products for {self.name}.")
        
        for i, prod_url in enumerate(urls_to_process):
            print(f"\n[{self.name}] Processing {i+1}/{len(urls_to_process)}... ({prod_url})")
            try:
                self.process_product(prod_url)
            except Exception as e:
                print(f"Error processing {prod_url}: {e}")
            time.sleep(0.5)

        if not DRY_RUN and LINK_ONLY_MODE:
            save_link_manifest()

    def get_all_product_urls(self) -> List[str]:
        return []
        
    def process_product(self, product_url: str):
        pass

    def _get_soup(self, url: str) -> Optional[BeautifulSoup]:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None


class GobildaScraper(BaseScraper):
    name = "goBILDA"
    base_url = "https://www.gobilda.com"
    
    def get_all_product_urls(self) -> List[str]:
        print("Fetching sitemap index from goBILDA...")
        index_url = "https://www.gobilda.com/xmlsitemap.php"
        all_urls: Set[str] = set()
        
        try:
            r = requests.get(index_url, timeout=10)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            sitemaps = root.findall('ns:sitemap/ns:loc', namespaces)
            if not sitemaps:
                sitemaps = [e for e in root.iter() if 'loc' in e.tag]
            target_sitemaps: List[str] = []
            for e in sitemaps:
                txt = e.text
                if txt and ('type=products' in txt or 'type=categories' in txt):
                    target_sitemaps.append(txt)
            
            for sm in target_sitemaps:
                if not sm: continue
                print(f"  -> Reading {sm}")
                sr = requests.get(sm, timeout=15)
                sr.raise_for_status()
                sroot = ET.fromstring(sr.content)
                
                locs = sroot.findall('ns:url/ns:loc', namespaces)
                if not locs:
                    locs = [e for e in sroot.iter() if 'loc' in e.tag]
                    
                for loc in locs:
                    txt = loc.text
                    if txt:
                        all_urls.add(txt)
        except Exception as e:
            print(f"Error fetching sitemap: {e}")
            
        return self._discover_all_pages(list(all_urls))
        
    def _spider_url(self, url: str, visited: Set[str]) -> Tuple[Set[str], Set[str]]:
        new_links: Set[str] = set()
        found_products: Set[str] = set()
        
        if url.count('/') >= 3:
             found_products.add(url)
             
        try:
            html = requests.get(url, timeout=10).text
            all_raw_links = set(re.findall(r'https://www\.gobilda\.com/[a-zA-Z0-9\-\/]+', html))
            
            for full_url in all_raw_links:
                if full_url not in visited:
                    skip_words = ['/login', '/cart', '/checkout', '/account', '/search', '/wishlist', '/policies', '/support', '/contact', '/blog', '/about', '.png', '.jpg', '.pdf', '/content/']
                    if not any(word in full_url.lower() for word in skip_words):
                        new_links.add(full_url)
        except Exception:
            pass
            
        return new_links, found_products
        
    def _discover_all_pages(self, start_urls: List[str]) -> List[str]:
        print(f"\nCrawling to find hidden variants (Starting with {len(start_urls)} URLs)...")
        visited: Set[str] = set()
        to_visit: Set[str] = set(start_urls)
        all_products: Set[str] = set()
        max_hops = 3
        
        for hop in range(max_hops):
            if not to_visit: break
            print(f"  Hop {hop+1}: Scanning {len(to_visit)} pages (This might take a minute)...")
            next_to_visit: Set[str] = set()
            
            current_batch = [url for url in to_visit if url not in visited]
            visited.update(current_batch)
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(self._spider_url, url, visited) for url in current_batch] # type: ignore
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        new_links, found_prods = future.result() # type: ignore
                        next_to_visit.update(new_links)
                        all_products.update(found_prods)
                    except Exception:
                        pass
            
            to_visit = next_to_visit
            
        all_products.update(start_urls) 
        final_products = []
        skip_words = ['/login', '/cart', '/checkout', '/account', '/search', '/wishlist', '/policies', '/support', '/contact', '/blog', '/about', '.png', '.jpg', '.pdf', '/content/']
        for p in all_products:
            if p.count('/') >= 3 and not any(word in p.lower() for word in skip_words):
                final_products.append(p)
        return list(set(final_products))
        
    def process_product(self, product_url: str):
        soup = self._get_soup(product_url)
        if not soup: return

        title_el = soup.select_one('h1.productView-title')
        if not title_el: return
        raw_name = title_el.text.strip()
        clean_name = clean_filename(raw_name)

        breadcrumbs = []
        bc_elements = soup.select('.breadcrumbs .breadcrumb a')
        for bc in bc_elements:
            text = bc.text.strip()
            if text.lower() not in ["home", "products"]: 
                breadcrumbs.append(normalize_category(text))
                
        if not breadcrumbs:
            breadcrumbs = guess_category_from_name(clean_name)

        step_link = None
        links = soup.select('a')
        for link in links:
            text = link.text.strip().lower()
            if "step file" in text:
                href = link.get('href')
                if href:
                    step_link = urljoin("https://www.gobilda.com", str(href))
                    break
                    
        if not step_link: return

        folder_path = os.path.join(DOWNLOAD_DIR, *breadcrumbs) # type: ignore
        fp_str = str(folder_path)
        if len(fp_str) > 150:
             folder_path = fp_str[:150]

        if not DRY_RUN:
            os.makedirs(folder_path, exist_ok=True)
        
        action = get_run_action_label()
        print(f"[{action}] {clean_name}")
        print(f"  -> Path: {folder_path}")
        print(f"  -> Link: {step_link}")

        if not DRY_RUN:
            if LINK_ONLY_MODE:
                handle_link_only_entry(step_link, str(folder_path), clean_name, product_url, self.name)
            else:
                expected_dest_path = os.path.join(folder_path, f"{clean_name}.step")
                if os.path.exists(expected_dest_path):
                    print(f"[SKIPPED] {clean_name} already exists.")
                    return
                if step_link:
                    download_cad_file(str(step_link), str(folder_path), clean_name)


class RevScraper(BaseScraper):
    name = "REV Robotics"
    base_url = "https://www.revrobotics.com"
    
    def get_all_product_urls(self) -> List[str]:
        print("Fetching sitemap from REV Robotics...")
        index_url = "https://www.revrobotics.com/xmlsitemap.php"
        all_urls: Set[str] = set()
        
        try:
            r = requests.get(index_url, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                
                sitemaps = root.findall('ns:sitemap/ns:loc', namespaces)
                if not sitemaps:
                    sitemaps = [e for e in root.iter() if 'loc' in e.tag]
            target_sitemaps: List[str] = []
            for e in sitemaps:
                txt = e.text
                if txt and ('type=products' in txt):
                    target_sitemaps.append(txt)
                
            for sm in target_sitemaps:
                    if not sm: continue
                    print(f"  -> Reading {sm}")
                    sr = requests.get(sm, timeout=15)
                    sroot = ET.fromstring(sr.content)
                    
                    locs = sroot.findall('ns:url/ns:loc', namespaces)
                    if not locs:
                        locs = [e for e in sroot.iter() if 'loc' in e.tag]
                        
                    for loc in locs:
                        txt = loc.text
                        if txt:
                            all_urls.add(txt)
        except Exception as e:
            print(f"Error fetching REV sitemap: {e}")
            
        return list(all_urls)
        
    def process_product(self, product_url: str):
        soup = self._get_soup(product_url)
        if not soup: return

        title_el = soup.select_one('h1.productView-title')
        if not title_el: return
        raw_name = title_el.text.strip()
        clean_name = clean_filename(raw_name)

        breadcrumbs = []
        bc_elements = soup.select('.breadcrumbs .breadcrumb a')
        for bc in bc_elements:
            text = bc.text.strip()
            if text.lower() not in ["home", "products", "ftc", "frc"]: 
                breadcrumbs.append(normalize_category(text))
                
        if not breadcrumbs:
            breadcrumbs = guess_category_from_name(clean_name)

        step_link = None
        # REV usually has STEP files labeled "STEP File" or ends with .step
        links = soup.select('a')
        for link in links:
            text = link.text.strip().lower()
            href = link.get('href', '')
            if "step" in text or href.lower().endswith('.step') or href.lower().endswith('.stp'):
                if href and not href.startswith('javascript'):
                    step_link = urljoin("https://www.revrobotics.com", str(href))
                    break
                    
        if not step_link: return

        folder_path = os.path.join(DOWNLOAD_DIR, *breadcrumbs) # type: ignore
        fp_str = str(folder_path)
        if len(fp_str) > 150:
             folder_path = fp_str[:150] # type: ignore

        if not DRY_RUN:
            os.makedirs(folder_path, exist_ok=True)
        
        action = get_run_action_label()
        print(f"[{action}] {clean_name}")
        print(f"  -> Path: {folder_path}")
        print(f"  -> Link: {step_link}")

        if not DRY_RUN:
            if LINK_ONLY_MODE:
                handle_link_only_entry(step_link, str(folder_path), clean_name, product_url, self.name)
            else:
                expected_dest_path = os.path.join(folder_path, f"{clean_name}.step")
                if os.path.exists(expected_dest_path):
                    print(f"[SKIPPED] {clean_name} already exists.")
                    return
                if step_link:
                    download_cad_file(str(step_link), str(folder_path), clean_name)


class AndyMarkScraper(BaseScraper):
    name = "AndyMark"
    base_url = "https://www.andymark.com"
    
    def get_all_product_urls(self) -> List[str]:
        print("Fetching sitemap from AndyMark...")
        index_url = "https://www.andymark.com/sitemap.xml" # They use Shopify style sitemap now
        all_urls: Set[str] = set()
        
        try:
            r = requests.get(index_url, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
                
                sitemaps = root.findall('ns:sitemap/ns:loc', namespaces)
                if not sitemaps:
                    sitemaps = [e for e in root.iter() if 'loc' in e.tag]
            target_sitemaps: List[str] = []
            for e in sitemaps:
                txt = e.text
                if txt and 'products' in txt:
                    target_sitemaps.append(txt)
                
            for sm in target_sitemaps:
                    if not sm: continue
                    print(f"  -> Reading {sm}")
                    sr = requests.get(sm, timeout=15)
                    sroot = ET.fromstring(sr.content)
                    
                    locs = sroot.findall('ns:url/ns:loc', namespaces)
                    if not locs:
                        locs = [e for e in sroot.iter() if 'loc' in e.tag]
                        
                    for loc in locs:
                        txt = loc.text
                        if txt:
                            all_urls.add(txt)
        except Exception as e:
            print(f"Error fetching AndyMark sitemap: {e}")
            
        return list(all_urls)
        
    def process_product(self, product_url: str):
        soup = self._get_soup(product_url)
        if not soup: return

        # AndyMark uses different classes sometimes
        title_el = soup.select_one('h1.product-title') 
        if not title_el:
            title_el = soup.select_one('h1')
            if not title_el: return
            
        raw_name = title_el.text.strip()
        clean_name = clean_filename(raw_name)

        breadcrumbs = []
        bc_elements = soup.select('.breadcrumb li a')
        for bc in bc_elements:
            text = bc.text.strip()
            if text.lower() not in ["home", "products", "all", "shop"]: 
                breadcrumbs.append(normalize_category(text))
                
        if not breadcrumbs:
            breadcrumbs = guess_category_from_name(clean_name)

        step_link = None
        links = soup.select('a')
        for link in links:
            text = link.text.strip().lower()
            href = link.get('href', '')
            if "step" in text or href.lower().endswith('.step') or href.lower().endswith('.stp'):
                if href and not href.startswith('javascript'):
                    step_link = urljoin("https://www.andymark.com", str(href))
                    break
                    
        if not step_link: return

        folder_path = os.path.join(DOWNLOAD_DIR, *breadcrumbs) # type: ignore
        fp_str = str(folder_path)
        if len(fp_str) > 150:
             folder_path = fp_str[:150] # type: ignore

        if not DRY_RUN:
            os.makedirs(folder_path, exist_ok=True)
        
        action = get_run_action_label()
        print(f"[{action}] {clean_name}")
        print(f"  -> Path: {folder_path}")
        print(f"  -> Link: {step_link}")

        if not DRY_RUN:
            if LINK_ONLY_MODE:
                handle_link_only_entry(step_link, str(folder_path), clean_name, product_url, self.name)
            else:
                expected_dest_path = os.path.join(folder_path, f"{clean_name}.step")
                if os.path.exists(expected_dest_path):
                    print(f"[SKIPPED] {clean_name} already exists.")
                    return
                download_cad_file(step_link, folder_path, clean_name)

def main():
    print("====================================")
    print("        CadGrab FTC Scraper         ")
    print("====================================")
    if DRY_RUN:
        print("!!! RUNNING IN DRY_RUN MODE. Files will NOT be downloaded. !!!")
    elif LINK_ONLY_MODE:
        print(f"!!! RUNNING IN LINK_ONLY_MODE. STEP files will not be downloaded locally.")
        print(f"!!! Link manifest will be written to: {LINK_MANIFEST_PATH}")
        load_link_manifest()
    
    print("\nSelect websites to scrape CAD parts from:")
    print("[1] goBILDA")
    print("[2] REV Robotics")
    print("[3] AndyMark")
    print("[4] ALL of the above")
    
    try:
        choice = input("\nEnter choice (1-4): ").strip()
    except EOFError:
        choice = "1"
        
    scrapers_to_run: List[BaseScraper] = []
    
    if choice == '1':
        scrapers_to_run.append(GobildaScraper())
    elif choice == '2':
        scrapers_to_run.append(RevScraper())
    elif choice == '3':
        scrapers_to_run.append(AndyMarkScraper())
    elif choice == '4':
        scrapers_to_run.append(GobildaScraper())
        scrapers_to_run.append(RevScraper())
        scrapers_to_run.append(AndyMarkScraper())
    else:
        print("Invalid choice. Defaulting to goBILDA.")
        scrapers_to_run.append(GobildaScraper())
        
    for scraper in scrapers_to_run:
        scraper.run()
        
    print("\nAll tasks completed!")

if __name__ == "__main__":
    main()
