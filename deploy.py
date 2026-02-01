# Run this as pyinfra deploy.py
from pyinfra.context import host
import pyinfra.facts as facts
from pyinfra.operations import apt, files, pip, server, systemd
from pyinfra.facts.files import Directory

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

files.directory(
    name="Ensure systemd drop-in directory for timeouts",
    path="/etc/systemd/system.conf.d",
    mode="755",
    _sudo=True,
)

systemd_timeout_changed = files.put(
    name="Shorten systemd default shutdown timeout",
    src="configs/systemd/boatpi-timeout.conf",
    dest="/etc/systemd/system.conf.d/boatpi.conf",
    mode="644",
    _sudo=True,
).changed

if systemd_timeout_changed:
    server.shell(
        name="Reload systemd manager configuration",
        commands=["systemctl daemon-reload"],
        _sudo=True,
    )

systemd.service(
    name="Enable and start mediamtx service",
    service="mediamtx",
    running=True,
    enabled=True,
    daemon_reload=mediamtx_service_changed,
    _sudo=True,
)

# Deploy MediaMTX adaptive bitrate controller
files.directory(
    name="Create bitrate controller directory",
    path="/opt/boatpi-qos",
    mode="755",
    user=host.get_fact(facts.server.User),
    _sudo=True,
)

qos_script_updated = files.put(
    name="Upload bitrate controller script",
    src="scripts/stream_qos.py",
    dest="/opt/boatpi-qos/stream_qos.py",
    mode="755",
    _sudo=True,
).changed

qos_service_changed = files.put(
    name="Upload bitrate controller systemd service",
    src="configs/stream-qos.service",
    dest="/etc/systemd/system/stream-qos.service",
    mode="644",
    _sudo=True,
).changed

systemd.service(
    name="Enable and start bitrate controller service",
    service="stream-qos",
    running=True,
    enabled=True,
    restarted=qos_script_updated,
    daemon_reload=qos_service_changed,
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

bootconfig_changed = False

bootconfig_changed = bootconfig_changed or files.replace(
    name="Disable camera auto detection in /boot/firmware/config.txt",
    path="/boot/firmware/config.txt",
    text="camera_auto_detect=1",
    replace="camera_auto_detect=0",
    _sudo=True,
).changed

bootconfig_changed = bootconfig_changed or files.line(
    name="Enable IMX708 Camera in /boot/firmware/config.txt",
    path="/boot/firmware/config.txt",
    line="dtoverlay=imx708",
    _sudo=True,
).changed

# Disable bluetooth to free up PL011 UART, and ensure its enabled
bootconfig_changed = bootconfig_changed or files.line(
    name="Disable bluetooth in /boot/firmware/config.txt",
    path="/boot/firmware/config.txt",
    line="dtoverlay=disable-bt",
    _sudo=True,
).changed

bootconfig_changed = bootconfig_changed or files.line(
    name="Enable GPIO shutdown on pin 3 in /boot/firmware/config.txt",
    path="/boot/firmware/config.txt",
    line="dtoverlay=gpio-shutdown,gpio_pin=3,active_low=1,gpio_pull=up",
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

# Check if wwan0 exists, if not, send the atcommands to create it
# We use NDIS mode rather than RNDIS mode as it seems to work better with NetworkManager
# RNDIS gives PPP errors when bringing the connection up with nmcli
wwan0_exists = host.get_fact(facts.hardware.NetworkDevices).get("wwan0")
if not wwan0_exists:
    server.shell(
        name="Switch LTE module to use NDIS mode",
        # Send command, wait for the module to restart
        commands=[
            'echo -e "AT+CUSBPIDSWITCH=9001,1,1\r\n" | tee /dev/ttyUSB2',
            'bash -c \'for i in {1..10}; do if ip link show wwan0 &>/dev/null; then exit 0; else sleep 3; fi; done; exit 1\''
        ],
        _sudo=True,
    )


#See if wwan0 has an ip address, if not, setup network manager for it
# Might also be called usb0 depending on mode
# Source: https://support.lenovo.com/gb/en/solutions/HT513050
wwan0_ip = host.get_fact(facts.hardware.Ipv4Addrs).get("wwan0")
if not wwan0_ip:
    # See https://wimsworld.wordpress.com/2023/12/21/revisiting-the-sim7600g-h-4g-hat-using-bookworm/
    # We need to delete any existing gsm connection first, then create a new one with the correct APN
    server.shell(
        name="Set the APN for the LTE connection",
        commands=[
            "nmcli con del gsm",
            "nmcli con add type gsm ifname '*' con-name 'gsm' apn 'mob.asm.net' connection.autoconnect yes",
            "nmcli con up gsm"
        ],
        _sudo=True,
    )

# Set higher metric on wwan0 to prefer wifi when both are connected
server.shell(
    name="Set higher metric on wwan0 interface",
    commands=[
        "nmcli connection modify gsm ipv4.route-metric 600",
        "nmcli connection modify gsm ipv6.route-metric 600",
    ],
    _sudo=True,
)

# Install mosh for better remote connections over LTE
apt.packages(
    name="Install mosh for better remote connections",
    packages=["mosh"],
    update=False, # Speeds up
    _sudo=True,
)

# Ensure venv tooling is present
apt.packages(
    name="Install python3-venv for signal monitor",
    packages=["python3-venv"],
    update=False,
    _sudo=True,
)

# Deploy Wi-Fi/LTE signal monitor daemon
files.directory(
    name="Create signal monitor directory",
    path="/opt/boatpi-signal",
    mode="755",
    user=host.get_fact(facts.server.User),
    _sudo=True,
)

signal_monitor_updated = files.put(
    name="Upload signal monitor script",
    src="scripts/signal_monitor.py",
    dest="/opt/boatpi-signal/signal_monitor.py",
    mode="755",
    _sudo=True,
).changed

venv_exists = host.get_fact(facts.files.Directory, path="/opt/boatpi-signal/venv")
venv_created = False
if not venv_exists:
    venv_created = server.shell(
        name="Create virtualenv for signal monitor",
        commands=["python3 -m venv /opt/boatpi-signal/venv"],
        _sudo=True,
    ).changed

pymavlink_installed = pip.packages(
    name="Install pymavlink in virtualenv",
    packages=["pymavlink"],
    virtualenv="/opt/boatpi-signal/venv",
    present=True,
    _sudo=True,
).changed

signal_service_changed = files.put(
    name="Upload signal monitor systemd service",
    src="configs/signal-monitor.service",
    dest="/etc/systemd/system/signal-monitor.service",
    mode="644",
    _sudo=True,
).changed

systemd.service(
    name="Enable and start signal monitor service",
    service="signal-monitor",
    running=True,
    enabled=True,
    restarted=signal_monitor_updated or venv_created or pymavlink_installed,
    daemon_reload=signal_service_changed,
    _sudo=True,
)