## Boatpi Config
Configuration for an autonomous boat's rasbperry pi zero 2W and [SIM7600 4G Hat](https://www.waveshare.com/wiki/SIM7600G-H_4G_HAT_(B)) using pyinfra

Likely not useful to anyone as is, but you can use this as inspiration maybe

Assumes you already have raspberry pi OS installed and SSH access, nothing else

### Features / TODO
- [X] Setup Arducam IMX 708 camera
- [X] Sets up low latency streaming using mediamtx
    - [X] Live adjust bit rate to keep ping to client below level via [scripts\stream_qos.py](scripts\stream_qos.py)
    - [X] Saves high-res (720p) video locally to `/var/log/mediamtx/` while streaming low-res to clients
- [X] Disables bluetooth to free up PL011 UART for flight controller
- [X] Sets up mavlink_router to route from UART to UDP/TCP
    - [X] Logs mavlink telemetry locally under `/var/log/mavlink-router`, keeping 2GB of space free
- [X] Sets up 4G Hat
    - [X] Sets higher metric on 4G connection so WiFi is preferred when present
- [X] Publishes Wi-Fi/LTE signal on MAVLink with [scripts\signal_monitor.py](scripts\signal_monitor.py)
    - [ ]TODO
- [X] GPIO shutdown by bridging pin 3 to ground
- [X] Speeds up shutdown by limiting process shutdown time to 10 seconds through a systemd manager drop-in (see [configs/systemd/boatpi-timeout.conf](configs/systemd/boatpi-timeout.conf#L1-L2))
- [X] Installs Mosh for more reliable remote shell over poor 4G connections
- [ ] TODO: Sets up tailscale for NAT punching / access via fixed DNS name (I use "boatpi")
- [ ] TODO: Set most of filesystem to readonly, apart from logs (hard to do while running from SD card!)


### Deployment
- Install pyinfra on your local machine (e.g. `uvx pyinfra`)
- Create an inventory.py of form `hosts=["your_rpi_address"]`
- Run `pyinfra inventory.py deploy.py`

### Video Playback
- Live streaming uses the `cam` path (scaled to `853x480` for low latency adaptive bitrate streaming).
- High resolution recording runs on `cam_record` (`1280x720`) and is saved automatically to `/var/log/mediamtx/` on the pi.
- For low (ish) latency playback, run `ffplay -fflags nobuffer -framedrop -flags low_delay rtsp://<device_tailscale_address>:8554/cam`
    - This is down to < 1 second over my rural LTE connection, which might be the limit
- Or even lower, but a bit glitchier (as `setpts=0` displays frames as soon as it has them, so framerate can be higher than 30fps) `ffplay -flags low_delay -vf setpts=0 -probesize 32 rtsp://<device>:8854/cam`
- QGroundControl can use RTSP on port 8554 `rtsp://boatpi:8554/cam`
- WebRTC is even better at `http://boatpi:8889/cam/`, but requires unreliable NAT punching connection over 4G/LTE

### Mavlink Connection
- Connect over UDP to port 10000. Ardupilot calls this "UDPCI" (client?) mode

### Signal strength -> MAVLink
- A systemd service `signal-monitor.service` polls every ~5s and sends MAVLink `NAMED_VALUE_FLOAT` messages over UDP to `127.0.0.1:14560` (arguments passed directly in the unit ExecStart; see file for overrides).
- Metrics:
    - `wifi_sig` (0-100% from `nmcli` of the active Wi‑Fi connection)
    - `lte_rssi`, `lte_rsrp`, `lte_rsrq`, `lte_snr` (from `mmcli --signal-get`, in dBm/dB)

### Issues
- Hardcodes APN/DNS instead of using pyinfra data file
- WebRTC takes a very long time to connect over LTE with tailscale sometimes doesn't work at all
- Non WebRTC streaming methods have very high (dozens of seconds) of lag

### Notes
- I am using 1password to manage my SSH keys, but this doesn't work so I have to use password auth (specify ssh_password in inventory.py, and enable it on the device). This might be related to https://github.com/paramiko/paramiko/issues/2370 as the error is the same.
- Inspired by Maverick's use of puppet, but no shared code. Commands in [raspberry.pp](https://github.com/goodrobots/maverick/blob/stable/manifests/maverick-modules/maverick_hardware/manifests/raspberry.pp) would have been a good source of inspiration had I seen them in advance
- Most of this was written by Github Copilot, using GPT-5.1-Codex / Mini / 5.2