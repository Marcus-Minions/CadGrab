import adsk.core, adsk.fusion, traceback
import os
import json
import tempfile
import urllib.request
import urllib.error
import ssl
import shutil
import zipfile
from urllib.parse import urlparse

_app = None
_ui = None
_handlers = []
_selected_folder = ""
_subdirs = []

class ImportExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            inputs = args.command.commandInputs
            
            # Find selected project
            proj_dropdown = inputs.itemById('project_select')
            selected_proj_name = proj_dropdown.selectedItem.name
            
            target_project = None
            for proj in _app.data.dataProjects:
                if proj.name == selected_proj_name:
                    target_project = proj
                    break
                    
            if not target_project:
                _ui.messageBox("Target project not found.")
                return
                
            # Find selected subdirs
            selected_subdirs = []
            for subdir in _subdirs:
                chk = inputs.itemById('chk_' + subdir)
                if chk and chk.value:
                    selected_subdirs.append(subdir)
                    
            import_root_files = False
            chk_root = inputs.itemById('chk_root_files')
            if chk_root and chk_root.value:
                import_root_files = True
                
            # Run the actual import job
            do_import(target_project, _selected_folder, selected_subdirs, import_root_files)
            
        except:
            _ui.messageBox('Failed during execution:\n{}'.format(traceback.format_exc()))

class ImportDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        # When UI dialog is closed, terminate the script
        adsk.terminate()

class ImportCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isReturnComplete = False
            
            # Hook up events
            onExecute = ImportExecuteHandler()
            cmd.execute.add(onExecute)
            _handlers.append(onExecute) # Keep handler in memory
            
            onDestroy = ImportDestroyHandler()
            cmd.destroy.add(onDestroy)
            _handlers.append(onDestroy)
            
            inputs = cmd.commandInputs
            
            # 1. Project Selection
            projInput = inputs.addDropDownCommandInput('project_select', 'Destination Project', adsk.core.DropDownStyles.TextListDropDownStyle)
            for proj in _app.data.dataProjects:
                projInput.listItems.add(proj.name, proj == _app.data.activeProject)
                
            # 2. Subdirectory Checkboxes
            if _subdirs:
                groupCmd = inputs.addGroupCommandInput('folders_group', 'Sub-Folders to Import')
                groupCmd.isExpanded = True
                for subdir in _subdirs:
                    groupCmd.children.addBoolValueInput('chk_' + subdir, subdir, True, '', True)
            
            # 3. Root files selection
            inputs.addBoolValueInput('chk_root_files', 'Import files in root folder', True, '', True)
            
        except:
            _ui.messageBox('Failed creating dialog:\n{}'.format(traceback.format_exc()))


def do_import(target_project, root_local_folder, selected_subdirs, import_root_files):
    targetProjectFolder = target_project.rootFolder
    link_manifest_path = os.path.join(root_local_folder, "cad_links_manifest.json")
    link_entries = []

    if os.path.exists(link_manifest_path):
        try:
            with open(link_manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            if isinstance(manifest_data, dict):
                for rel_path, info in manifest_data.items():
                    if not isinstance(rel_path, str) or not isinstance(info, dict):
                        continue
                    url = info.get("url")
                    if not isinstance(url, str) or not url:
                        continue
                    if not rel_path.lower().endswith((".step", ".stp")):
                        continue
                    norm_rel_path = rel_path.replace("\\", "/").strip("/")
                    if not norm_rel_path:
                        continue
                    parts = [p for p in norm_rel_path.split("/") if p and p != "." and p != ".."]
                    if not parts:
                        continue
                    file_name = parts[-1]
                    folder_parts = parts[:-1]
                    if folder_parts and folder_parts[0] not in selected_subdirs:
                        continue
                    if not folder_parts and not import_root_files:
                        continue
                    parsed = urlparse(url)
                    if parsed.scheme not in ("http", "https"):
                        continue
                    link_entries.append({
                        "file_name": file_name,
                        "folder_parts": folder_parts,
                        "url": url
                    })
        except (json.JSONDecodeError, OSError, ValueError) as e:
            _ui.messageBox(f"Failed to parse cad_links_manifest.json ({e}).\nFalling back to local file import.")
            link_entries = []
    
    progressDialog = _ui.createProgressDialog()
    progressDialog.cancelButtonText = 'Cancel'
    progressDialog.isBackgroundDependent = False
    progressDialog.isCancelButtonShown = True

    # Build a deep scan list to count files properly
    total_files = 0
    
    if link_entries:
        total_files = len(link_entries)
    else:
        if import_root_files:
            for item in os.listdir(root_local_folder):
                if os.path.isfile(os.path.join(root_local_folder, item)) and item.lower().endswith(('.step', '.stp')):
                    total_files += 1

        for subdir in selected_subdirs:
             scan_path = os.path.join(root_local_folder, subdir)
             for root, dirs, files in os.walk(scan_path):
                 for file in files:
                     if file.lower().endswith(('.step', '.stp')):
                         total_files += 1
                     
    if total_files == 0:
         _ui.messageBox("No STEP files found in the selected directories!")
         return
                        
    progressDialog.show('Bulk Importing Models...', 'Initializing...', 0, total_files, 1)
    
    files_imported = 0
    files_skipped = 0
    files_failed = 0
    
    # Cloud Caching System! Extremely important for performance.
    # Key: dataFolder.id, Value: { "folders": {name: DataFolder}, "files": {name: bool} }
    folder_cache = {}
    
    def get_cloud_contents(cloud_folder):
        if cloud_folder.id not in folder_cache:
            progressDialog.message = f'Scanning cloud index for: {cloud_folder.name}...'
            adsk.doEvents()
            
            folders = {}
            for df in cloud_folder.dataFolders:
                 folders[df.name] = df
                 
            files = {}
            for df in cloud_folder.dataFiles:
                 files[df.name] = True # Just mark it exists
                 
            folder_cache[cloud_folder.id] = { "folders": folders, "files": files }
            
        return folder_cache[cloud_folder.id]

    def download_step_from_url(url):
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        request = urllib.request.Request(url, headers={"User-Agent": "CadGrab-Fusion-Importer"})
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            status_code = response.getcode()
            if status_code and not (200 <= status_code < 300):
                raise ValueError(f"HTTP status {status_code}")

            content_type = response.headers.get("Content-Type", "").lower()
            is_zip = url.lower().endswith(".zip") or "zip" in content_type

            if "text/html" in content_type:
                raise ValueError("Unexpected HTML response for STEP download")

            if is_zip:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_zip:
                    shutil.copyfileobj(response, tmp_zip)
                    zip_path = tmp_zip.name
                try:
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        step_files = [f for f in zip_ref.namelist() if f.lower().endswith((".step", ".stp"))]
                        if not step_files:
                            raise ValueError("No STEP/STP file found in ZIP")
                        selected_step = step_files[0]
                        normalized = selected_step.replace("\\", "/")
                        if normalized.startswith("/") or any(part == ".." for part in normalized.split("/")):
                            raise ValueError("Unsafe STEP path in ZIP")
                        with zip_ref.open(selected_step) as source:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp_step:
                                shutil.copyfileobj(source, tmp_step)
                                return tmp_step.name
                finally:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".step") as tmp_step:
                shutil.copyfileobj(response, tmp_step)
                return tmp_step.name
        

    def process_directory(local_path, current_cloud_folder, is_root=False):
        nonlocal files_imported, files_skipped
        
        if progressDialog.wasCancelled:
             return
             
        # Ask cloud for files exactly once per folder, storing in dictionary
        cloud_contents = get_cloud_contents(current_cloud_folder)
        
        # Iterating over local files
        for item in os.listdir(local_path):
            if progressDialog.wasCancelled:
                return
                
            full_path = os.path.join(local_path, item)
            
            if os.path.isdir(full_path):
                # Only process this subdirectory if it was checked in the UI!
                if is_root and item not in selected_subdirs:
                    continue
                    
                next_cloud_folder = cloud_contents["folders"].get(item)
                
                # If folder doesn't exist in cloud, create it and add to our cache!
                if not next_cloud_folder:
                     progressDialog.message = f'Creating cloud directory: {item}...'
                     adsk.doEvents()
                     next_cloud_folder = current_cloud_folder.dataFolders.add(item)
                     cloud_contents["folders"][item] = next_cloud_folder
                     
                # Recurse deeper!
                process_directory(full_path, next_cloud_folder, is_root=False)
                
            elif os.path.isfile(full_path) and item.lower().endswith(('.step', '.stp')):
                # Only import root files if checkbox was checked
                if is_root and not import_root_files:
                    continue
                    
                base_name = os.path.splitext(item)[0]
                
                # Check cache for existence (Instant dictionary lookup)
                # Fusion sometimes names the file with or without the extension in the data panel
                if base_name in cloud_contents["files"] or item in cloud_contents["files"]:
                    files_skipped += 1
                else:
                    progressDialog.message = f'Uploading file: {item}...'
                    adsk.doEvents()
                    
                    try:
                        # uploadFile is the correct method for raw STEP files to the Data Panel
                        current_cloud_folder.uploadFile(full_path)
                        
                        # Add newly uploaded file to cache so we don't duplicate it later
                        cloud_contents["files"][base_name] = True
                        cloud_contents["files"][item] = True
                        files_imported += 1
                    except Exception as e:
                        # Continue even if one specific file breaks
                        pass
                    
                progressDialog.progressValue = files_imported + files_skipped
                adsk.doEvents()

    def process_link_entries(current_cloud_folder):
        nonlocal files_imported, files_skipped, files_failed

        for entry in link_entries:
            if progressDialog.wasCancelled:
                return

            file_name = entry["file_name"]
            folder_parts = entry["folder_parts"]
            file_url = entry["url"]

            destination_folder = current_cloud_folder
            for folder_name in folder_parts:
                cloud_contents = get_cloud_contents(destination_folder)
                next_cloud_folder = cloud_contents["folders"].get(folder_name)
                if not next_cloud_folder:
                    progressDialog.message = f'Creating cloud directory: {folder_name}...'
                    adsk.doEvents()
                    next_cloud_folder = destination_folder.dataFolders.add(folder_name)
                    cloud_contents["folders"][folder_name] = next_cloud_folder
                destination_folder = next_cloud_folder

            cloud_contents = get_cloud_contents(destination_folder)
            base_name = os.path.splitext(file_name)[0]
            if base_name in cloud_contents["files"] or file_name in cloud_contents["files"]:
                files_skipped += 1
            else:
                progressDialog.message = f'Uploading from link: {file_name}...'
                adsk.doEvents()

                temp_file_path = None
                try:
                    temp_file_path = download_step_from_url(file_url)
                    destination_folder.uploadFile(temp_file_path)
                    cloud_contents["files"][base_name] = True
                    cloud_contents["files"][file_name] = True
                    files_imported += 1
                except (urllib.error.URLError, OSError, ValueError) as e:
                    files_failed += 1
                    print(f"[FAILED] Could not import '{file_name}' into folder '{destination_folder.name}' from link '{file_url}' ({e})")
                finally:
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.remove(temp_file_path)
                        except OSError as e:
                            print(f"[WARN] Could not remove temp file '{temp_file_path}' ({e})")

            progressDialog.progressValue = files_imported + files_skipped + files_failed
            adsk.doEvents()

    # Start the engine!
    if link_entries:
        process_link_entries(targetProjectFolder)
    else:
        process_directory(root_local_folder, targetProjectFolder, is_root=True)
    
    progressDialog.hide()
    
    if progressDialog.wasCancelled:
         _ui.messageBox(f'Import cancelled.\nUploaded: {files_imported}\nSkipped (Duplicates): {files_skipped}\nFailed: {files_failed}')
    else:
         _ui.messageBox(f'Import Complete!\nUploaded: {files_imported}\nSkipped (Duplicates): {files_skipped}\nFailed: {files_failed}')


def run(context):
    global _app, _ui, _selected_folder, _subdirs
    try:
        _app = adsk.core.Application.get()
        _ui  = _app.userInterface
        
        # 1. Ask user for the generic directory 
        folderDialog = _ui.createFolderDialog()
        folderDialog.title = 'Select ANY local folder containing 3D models'
        dialogResult = folderDialog.showDialog()
        
        if dialogResult == adsk.core.DialogResults.DialogOK:
            _selected_folder = folderDialog.folder
        else:
             return # User cancelled right away
             
        # 2. Extract first-level subdirectories for the UI checkboxes
        _subdirs = []
        for item in os.listdir(_selected_folder):
             if os.path.isdir(os.path.join(_selected_folder, item)):
                  _subdirs.append(item)
                  
        _subdirs.sort()

        # 3. Create the Custom Command Dialog GUI
        cmdDef = _ui.commandDefinitions.itemById('genericBulkImportCmd')
        if cmdDef:
             cmdDef.deleteMe()
             
        cmdDef = _ui.commandDefinitions.addButtonDefinition('genericBulkImportCmd', 'Bulk Import 3D Models', 'Imports a generic folder structure of CAD models to the cloud.')
        
        onCommandCreated = ImportCommandCreatedHandler()
        cmdDef.commandCreated.add(onCommandCreated)
        _handlers.append(onCommandCreated)
        
        cmdDef.execute()
        
        # Tell Fusion to keep the script running while the dialog is active
        adsk.autoTerminate(False)

    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        cmdDef = _ui.commandDefinitions.itemById('genericBulkImportCmd')
        if cmdDef:
            cmdDef.deleteMe()
    except:
        pass
