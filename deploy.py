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
mediamtx_service_changed = files.put(
    name="Upload mediamtx systemd service",
    src="configs/mediamtx.service",
    dest="/etc/systemd/system/mediamtx.service",
    mode="644",
    _sudo=True,
).changed

systemd.service(
    name="Enable and start mediamtx service",
    service="mediamtx",
    running=True,
    enabled=True,
    daemon_reload=mediamtx_service_changed,
    _sudo=True,
)

# Ensure current user is in dialout group for serial port access
server.user(
    name="Add boatpi user to dialout group",
    user=host.get_fact(facts.server.User),
    groups=["dialout"],
    append=True,
    _sudo=True,
)

# Disable bluetooth to free up PL011 UART, and ensure its enabled
bootconfig_changed = files.line(
    name="Disable bluetooth in /boot/firmware/config.txt",
    path="/boot/firmware/config.txt",
    line="dtoverlay=disable-bt",
    _sudo=True,
).changed

if bootconfig_changed:
    server.shell(
    name="Enable serial hardware",
    commands=[
        "raspi-config nonint do_serial_hw 0",
    ],
        _sudo=True,
    )

    server.shell(
        name="Disable serial console",
        commands=[
            "raspi-config nonint do_serial_cons 1",
        ],
        _sudo=True,
    )

    server.reboot(
        name="Reboot to apply boot configuration changes",
        delay=5,
        _sudo=True,
    )

systemd.service(
    name="Disable bluetooth service",
    service="hciuart",
    running=False,
    enabled=False,
    _sudo=True,
)

# Install mavlink-router
files.download(
    name="Download mavlink-router package",
    src="https://github.com/mavlink-router/mavlink-router/releases/download/v4/mavlink-routerd-glibc-aarch64",
    dest="/usr/local/bin/mavlink-routerd",
    _sudo=True,
    mode="755", # Executable
    sha256sum="fad7a5ee509cdcbd1b4569c2d9da356b901f2d521d45c970473ceb6f5b8e0619"
)

# Copy across mavlink-router configuration
mavlink_config_changed = files.put(
    name="Upload mavlink-router configuration",
    src="configs/mavlink-router/main.conf", 
    dest="/etc/mavlink-router/main.conf",
    _sudo=True,
    mode="644", # Readable by all users
).changed

mavlink_service_changed = files.put(
    name="Upload mavlink-router systemd service",
    src="configs/mavlink-router.service",
    dest="/etc/systemd/system/mavlink-router.service",
    mode="644",
    _sudo=True,
).changed

systemd.service(
    name="Enable and start mavlink-router service",
    service="mavlink-router",
    running=True,
    enabled=True,
    restarted=mavlink_config_changed,
    daemon_reload=mavlink_service_changed,
    _sudo=True,
)
