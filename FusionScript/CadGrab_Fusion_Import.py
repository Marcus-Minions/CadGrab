import adsk.core, adsk.fusion, traceback
import os

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
        pass # App stays alive for the background API!

class ImportCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            cmd = args.command
            cmd.isReturnComplete = False
            
            # Prompt folder before drawing inputs
            global _selected_folder, _subdirs
            folderDialog = _ui.createFolderDialog()
            folderDialog.title = 'Select ANY local folder containing 3D models'
            if folderDialog.showDialog() == adsk.core.DialogResults.DialogOK:
                _selected_folder = folderDialog.folder
                _subdirs = []
                for item in os.listdir(_selected_folder):
                     if os.path.isdir(os.path.join(_selected_folder, item)):
                          _subdirs.append(item)
                _subdirs.sort()
            
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
    importManager = _app.importManager
    targetProjectFolder = target_project.rootFolder
    
    progressDialog = _ui.createProgressDialog()
    progressDialog.cancelButtonText = 'Cancel'
    progressDialog.isBackgroundDependent = False
    progressDialog.isCancelButtonShown = True

    # Build a deep scan list to count files properly
    total_files = 0
    
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

    # Start the engine!
    process_directory(root_local_folder, targetProjectFolder, is_root=True)
    
    progressDialog.hide()
    
    if progressDialog.wasCancelled:
         _ui.messageBox(f'Import cancelled.\nUploaded: {files_imported}\nSkipped (Duplicates): {files_skipped}')
    else:
         _ui.messageBox(f'Import Complete!\nUploaded: {files_imported}\nSkipped (Duplicates): {files_skipped}')

class CadGrabFetchPartHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            import json, ssl, urllib.request, re, tempfile, zipfile
            from urllib.parse import urljoin
            
            payload = json.loads(args.additionalInfo)
            supplier = payload.get("supplier", "").lower()
            part_number = payload.get("part_number", "")
            
            if not supplier or not part_number: return

            cache_dir = os.path.join(tempfile.gettempdir(), 'CadGrab_Cache')
            os.makedirs(cache_dir, exist_ok=True)
            final_step_path = os.path.join(cache_dir, f"{supplier}_{part_number}.step".replace('/', '_').replace('\\', '_'))
            
            if not os.path.exists(final_step_path):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                
                domain, search_url = "", ""
                if "gobilda" in supplier:
                    domain = "https://www.gobilda.com"
                    search_url = f"{domain}/search.php?search_query={part_number}"
                elif "rev" in supplier:
                    domain = "https://www.revrobotics.com"
                    search_url = f"{domain}/search.php?search_query={part_number}"
                elif "andy" in supplier:
                    domain = "https://www.andymark.com"
                    search_url = f"{domain}/search?q={part_number}"
                else:
                    return
                    
                req = urllib.request.Request(search_url, headers=headers)
                resp = urllib.request.urlopen(req, context=ctx)
                html = resp.read().decode('utf-8')
                
                file_link = None
                
                # Check for direct STEP text matches first:
                matches = re.finditer(r'<a[^>]+href=[\'\"]([^\'\"]+)[\'\"][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
                for m in matches:
                    if 'STEP' in m.group(2).upper():
                        file_link = m.group(1)
                        break
                        
                if not file_link:
                    links = re.findall(r'href=[\'\"]([^\'\"]+\.(?:step|stp|zip))[\'\"]', html, re.IGNORECASE)
                    if links: file_link = links[0]
                    
                if not file_link:
                     prod_links = []
                     if "gobilda" in supplier:
                         prod_links = re.findall(r'href=[\'\"](https://www\.gobilda\.com/[^\'\"]+)[\'\"]', html)
                     elif "rev" in supplier:
                         prod_links = re.findall(r'href=[\'\"](https://www\.revrobotics\.com/[^\'\"]+)[\'\"]', html)
                     elif "andy" in supplier:
                         prod_links = re.findall(r'href=[\'\"](/products/[^\'\"]+)[\'\"]', html)
                         
                     for pl in prod_links:
                         if part_number.lower() in pl.lower() and "search" not in pl.lower():
                             if pl.startswith('/'): pl = domain + pl
                             req2 = urllib.request.Request(pl, headers=headers)
                             resp2 = urllib.request.urlopen(req2, context=ctx)
                             html2 = resp2.read().decode('utf-8')
                             matches2 = re.finditer(r'<a[^>]+href=[\'\"]([^\'\"]+)[\'\"][^>]*>(.*?)</a>', html2, re.IGNORECASE | re.DOTALL)
                             for m2 in matches2:
                                 if 'STEP' in m2.group(2).upper():
                                     file_link = m2.group(1)
                                     break
                             if not file_link:
                                 links2 = re.findall(r'href=[\'\"]([^\'\"]+\.(?:step|stp|zip))[\'\"]', html2, re.IGNORECASE)
                                 if links2: file_link = links2[0]
                             if file_link: break
                             
                if file_link:
                     if not file_link.startswith('http'):
                         file_link = urljoin(domain, file_link)
                     req3 = urllib.request.Request(file_link, headers=headers)
                     resp3 = urllib.request.urlopen(req3, context=ctx)
                     is_zip = file_link.lower().endswith('.zip') or 'zip' in resp3.headers.get('Content-Type', '').lower()
                     if is_zip:
                         tmp_zip = os.path.join(cache_dir, f"{part_number}_temp.zip")
                         with open(tmp_zip, 'wb') as f: f.write(resp3.read())
                         with zipfile.ZipFile(tmp_zip, 'r') as zf:
                             step_files = [n for n in zf.namelist() if n.lower().endswith(('.step', '.stp'))]
                             if step_files:
                                 with zf.open(step_files[0]) as source, open(final_step_path, 'wb') as target:
                                     target.write(source.read())
                         os.remove(tmp_zip)
                     else:
                         with open(final_step_path, 'wb') as f:
                             f.write(resp3.read())
                             
            if os.path.exists(final_step_path):
                 app = adsk.core.Application.get()
                 des = adsk.fusion.Design.cast(app.activeProduct)
                 if des:
                     importManager = app.importManager
                     rootComp = des.rootComponent
                     options = importManager.createSTEPImportOptions(final_step_path)
                     importManager.importToTarget(options, rootComp)
                     success_event = app.customEvents.itemById('CadGrab_FetchPart_Success_Event')
                     if success_event:
                         success_event.fire(json.dumps({"part_number": part_number, "status": "success"}))
        except Exception:
             pass # Headless fail silently

def run(context):
    global _app, _ui, _selected_folder, _subdirs
    try:
        _app = adsk.core.Application.get()
        _ui  = _app.userInterface
        
        try:
            fetchEvent = _app.registerCustomEvent('CadGrab_FetchPart_Event')
            if fetchEvent:
                onFetch = CadGrabFetchPartHandler()
                fetchEvent.add(onFetch)
                _handlers.append(onFetch)
            _app.registerCustomEvent('CadGrab_FetchPart_Success_Event')
        except: pass
        
        cmdDef = _ui.commandDefinitions.itemById('cadGrabBulkImportCmd')
        if cmdDef: cmdDef.deleteMe()
             
        cmdDef = _ui.commandDefinitions.addButtonDefinition('cadGrabBulkImportCmd', 'CadGrab Bulk Import', 'Imports a generic folder structure of CAD models to the cloud.')
        
        onCommandCreated = ImportCommandCreatedHandler()
        cmdDef.commandCreated.add(onCommandCreated)
        _handlers.append(onCommandCreated)
        
        panel = _ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        if panel:
            control = panel.controls.itemById('cadGrabBulkImportCmd')
            if control: control.deleteMe()
            panel.controls.addCommand(cmdDef)

    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    try:
        cmdDef = _ui.commandDefinitions.itemById('cadGrabBulkImportCmd')
        if cmdDef: cmdDef.deleteMe()
        panel = _ui.allToolbarPanels.itemById('SolidScriptsAddinsPanel')
        if panel:
            control = panel.controls.itemById('cadGrabBulkImportCmd')
            if control: control.deleteMe()
            
        _app = adsk.core.Application.get()
        _app.unregisterCustomEvent('CadGrab_FetchPart_Event')
        _app.unregisterCustomEvent('CadGrab_FetchPart_Success_Event')
    except:
        pass
