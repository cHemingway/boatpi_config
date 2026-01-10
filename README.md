## Boatpi Config
Configuration for an autonomous boat's rasbperry pi zero 2W and [SIM7600 4G Hat](https://www.waveshare.com/wiki/SIM7600G-H_4G_HAT_(B)) using pyinfra

Likely not useful to anyone as is, but you can use this as inspiration maybe

Assumes you already have raspberry pi OS installed and SSH access, nothing else

### Features / TODO
- [X] Setup IMX 708 camera
- [X] Sets up low latency streaming using mediamtx
    - [ ] Logs video locally
- [X] Disables bluetooth to free up PL011 UART for flight controller
- [X] Sets up mavlink_router
    - [ ] Turns on local flight logs
- [X] Sets up 4G Hat
- [X] Publishes Wi-Fi/LTE signal to MAVLink (127.0.0.1:14560)
- [X] GPIO shutdown by bridging pin 3 to ground
- [ ] Sets up tailscale for NAT punching
- [ ] Set most of filesystem to readonly


### Deployment
- Install pyinfra on your local machine (e.g. `uvx pyinfra`)
- Create an inventory.py of form `hosts=["your_rpi_address"]`
- Run `pyinfra inventory.py deploy.py`

### Using 
- For low (ish) latency playback, run `ffplay -fflags nobuffer -framedrop -flags low_delay rtsp://<device_tailscale_address>:8554/cam`
    - This is down to < 1 second over my rural LTE connection, which might be the limit
- Or even lower, but a bit glitchier (as `setpts=0` displays frames as soon as it has them, so framerate can be higher than 30fps) `ffplay -flags low_delay -vf setpts=0 -probesize 32 rtsp://<device>:8854/cam`

### Signal strength -> MAVLink

- A systemd service `signal-monitor.service` polls every ~5s and sends MAVLink `NAMED_VALUE_FLOAT` messages over UDP to `127.0.0.1:14560` (arguments passed directly in the unit ExecStart; see file for overrides).
- Metrics:
    - `wifi_sig` (0-100% from `nmcli` of the active Wi‑Fi connection)
    - `lte_rssi`, `lte_rsrp`, `lte_rsrq`, `lte_snr` (from `mmcli --signal-get`, in dBm/dB)
- The service depends on NetworkManager + ModemManager and runs from a venv at `/opt/boatpi-signal/venv` with `pymavlink` installed via pip.
- On target: `sudo systemctl status signal-monitor` or `journalctl -u signal-monitor -f`.


### Issues
- Hardcodes APN/DNS instead of using pyinfra data file
- WebRTC takes a very long time to connect over LTE with tailscale sometimes doesn't work at all
- Non WebRTC streaming methods have very high (dozens of seconds) of lag
- LTE is the default route if available even when WiFi comes back, which makes programs that download things (e.g. apt) download over LTE instead which is much slower


### Notes
- I am using 1password to manage my SSH keys, but this doesn't work so I have to use password auth (specify ssh_password in inventory.py, and enable it on the device). This might be related to https://github.com/paramiko/paramiko/issues/2370 as the error is the same.
- Inspired by Maverick's use of puppet, but no shared code. Commands in [raspberry.pp](https://github.com/goodrobots/maverick/blob/stable/manifests/maverick-modules/maverick_hardware/manifests/raspberry.pp) would have been a good source of inspiration had I seen them in advance
- Signal monitor script was written by GPT-5.1-Codex and Copilot