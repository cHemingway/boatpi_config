# Run this as pyinfra deploy.py
from pyinfra.context import host
import pyinfra.facts as facts
from pyinfra.operations import apt, files, server, systemd

# Check that we are on the correct architecture
assert host.get_fact(facts.server.Arch) == "aarch64", "This deploy script is intended for aarch64 only"


# Install mediamtx
files.directory(
    name="Create mediamtx directory",
    path="/opt/mediamtx",
    mode="755",
    user=host.get_fact(facts.server.User),
    _sudo=True,
)

mediamtx_downloaded = files.download(
    name="Download mediamtx binary",
    src="https://github.com/bluenviron/mediamtx/releases/download/v1.15.3/mediamtx_v1.15.3_linux_arm64.tar.gz",
    dest="/opt/mediamtx/mediamtx.tar.gz",
    sha256sum="5f3cb84ef42952a82b1ff5764fd06dc13697d21b06eb179d83663ec55d15ed0c",
)

if mediamtx_downloaded.changed:
    server.shell(
        name="Extract mediamtx binary",
        commands=[
            "tar -xzf /opt/mediamtx/mediamtx.tar.gz -C /opt/mediamtx/",
            "chmod +x /opt/mediamtx/mediamtx",
        ],
    )
    
# Update mediamtx configuration
files.put(
    name="Upload mediamtx configuration",
    src="configs/mediamtx.yml",
    dest="/opt/mediamtx/mediamtx.yml",
    mode="644", # Readable by all users
)

# Setup mediamtx as a systemd service
files.put(
    name="Upload mediamtx systemd service",
    src="configs/mediamtx.service",
    dest="/etc/systemd/system/mediamtx.service",
    mode="644",
    _sudo=True,
)

systemd.service(
    name="Enable and start mediamtx service",
    service="mediamtx",
    running=True,
    enabled=True,
    _sudo=True,
)