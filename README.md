## Boatpi Config
Configuration for an autonomous boat's rasbperry pi zero 2W using pyinfra

Likely not useful to anyone as is, but you can use this as inspiration maybe

Assumes you already have raspberry pi OS installed and SSH access, nothing else

### Features
- [X] Sets up low latency streaming using mediamtx
- [X] Disables bluetooth to free up PL011 UART for flight controller
- [X] Sets up mavlink_router
- [ ] Sets up 4G modem
- [ ] Sets up tailscale for NAT punching

### Usage
- Install pyinfra on your local machine (e.g. `uvx tool install pyinfra`)
- Create an inventory.py of form `hosts=["your_rpi_address"]`
- Run `pyinfra inventory.py deploy.py`

### Notes
- I am using 1password to manage my SSH keys, but this doesn't work so I have to use password auth (specify ssh_password in inventory.py, and enable it on the device). This might be related to https://github.com/paramiko/paramiko/issues/2370 as the error is the same.