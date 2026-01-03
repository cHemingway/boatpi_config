## Boatpi Config
Configuration for an autonomous boat's rasbperry pi zero 2W and [SIM7600 4G Hat](https://www.waveshare.com/wiki/SIM7600G-H_4G_HAT_(B)) using pyinfra

Likely not useful to anyone as is, but you can use this as inspiration maybe

Assumes you already have raspberry pi OS installed and SSH access, nothing else

### Features / TODO
- [X] Sets up low latency streaming using mediamtx
    - [ ] Logs video locally
- [X] Disables bluetooth to free up PL011 UART for flight controller
- [X] Sets up mavlink_router
    - [ ] Turns on local flight logs
- [X] Sets up 4G Hat
- [ ] Sets up tailscale for NAT punching
- [ ] Push 4G signal to mavlink-router [using mmcli](https://unix.stackexchange.com/questions/586528/gsm-modem-get-signal-strength)
- [ ] Set most of filesystem to readonly
- [ ] Add a way of turning off the pi that isn't via SSH, pushbutton?

### Deployment
- Install pyinfra on your local machine (e.g. `uvx pyinfra`)
- Create an inventory.py of form `hosts=["your_rpi_address"]`
- Run `pyinfra inventory.py deploy.py`

### Using 
- For low (ish) latency playback, run `ffplay -fflags nobuffer -framedrop -flags low_delay rtsp://<device_tailscale_address>:8554/cam`
    - This is down to < 1 second over my rural LTE connection, which might be the limit
- Or even lower, but a bit glitchier (as `setpts=0` displays frames as soon as it has them, so framerate can be higher than 30fps) `ffplay -flags low_delay -vf setpts=0 -probesize 32 rtsp://<device>:8854/cam`


### Issues
- Hardcodes APN/DNS instead of using pyinfra data file
- WebRTC takes a very long time to connect over LTE with tailscale sometimes doesn't work at all
- Non WebRTC streaming methods have very high (dozens of seconds) of lag
- LTE is the default route if available even when WiFi comes back, which makes programs that download things (e.g. apt) download over LTE instead which is much slower


### Notes
- I am using 1password to manage my SSH keys, but this doesn't work so I have to use password auth (specify ssh_password in inventory.py, and enable it on the device). This might be related to https://github.com/paramiko/paramiko/issues/2370 as the error is the same.
- Inspired by Maverick's use of puppet, but no shared code. Commands in [raspberry.pp](https://github.com/goodrobots/maverick/blob/stable/manifests/maverick-modules/maverick_hardware/manifests/raspberry.pp) would have been a good source of inspiration had I seen them in advance