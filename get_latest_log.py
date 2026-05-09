# pyinfra operation to fetch latest logs from /var/log/mavlink-router to ./logs
import os
import re
from pyinfra import host
from pyinfra.operations import files, server
from pyinfra.facts.files import FindFiles, File

# To delete video after downloading, pass --data delete_video=true
DELETE_VIDEO = str(host.data.get('delete_video', '')).strip().lower() in ('1', 'true', 'yes', 'y')

# Remote directories
remote_mavlink_dir = '/var/log/mavlink-router'
remote_video_dir = '/var/log/mediamtx/cam_record'

def get_latest_file(remote_dir, extension=None):
    file_paths = host.get_fact(FindFiles, remote_dir)
    if not file_paths:
        return None
    
    file_mtimes = []
    for path in file_paths:
        if extension and not path.endswith(extension):
            continue
        info = host.get_fact(File, path)
        if info and info != False:
            file_mtimes.append((path, info['mtime']))
            
    if not file_mtimes:
        return None
        
    sorted_files = sorted(file_mtimes, key=lambda x: x[1], reverse=True)
    return sorted_files[0][0]

latest_tlog_path = get_latest_file(remote_mavlink_dir)
latest_mp4_path = get_latest_file(remote_video_dir, extension=".mp4")

# Determine a common directory name based on tlog date, or just mp4 date
folder_name = "latest_session"
if latest_tlog_path:
    # Try to extract date from tlog: e.g. 00019-2026-04-17_20-47-14.tlog
    match = re.search(r'\d+-(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', latest_tlog_path)
    if match:
        folder_name = match.group(1)
elif latest_mp4_path:
    match = re.search(r'(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', latest_mp4_path)
    if match:
        folder_name = match.group(1)

# Ensure local logs directory exists
local_session_dir = os.path.join(os.getcwd(), 'logs', folder_name)
os.makedirs(local_session_dir, exist_ok=True)

if latest_tlog_path:
    local_tlog_path = os.path.join(local_session_dir, os.path.basename(latest_tlog_path))
    files.get(
        name=f"Download latest tlog: {os.path.basename(latest_tlog_path)}",
        src=latest_tlog_path,
        dest=local_tlog_path,
    )
else:
    print(f"No log files found in {remote_mavlink_dir}.")

if latest_mp4_path:
    local_mp4_path = os.path.join(local_session_dir, os.path.basename(latest_mp4_path))
    files.get(
        name=f"Download latest MP4: {os.path.basename(latest_mp4_path)}",
        src=latest_mp4_path,
        dest=local_mp4_path,
    )
    if DELETE_VIDEO:
        files.file(
            name=f"Delete remote video: {latest_mp4_path}",
            path=latest_mp4_path,
            present=False,
            _sudo=True
        )
else:
    print(f"No video files found in {remote_video_dir}.")
