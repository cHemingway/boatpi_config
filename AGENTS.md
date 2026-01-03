### Context & Workflow
- This repo is a pyinfra playbook that configures a Raspberry Pi Zero 2W (aarch64) with camera streaming, MAVLink routing, and LTE telemetry; run deployments locally with `uvx pyinfra inventory.py deploy.py` after editing [inventory.py](inventory.py) for target hosts.
- All operations in [deploy.py](deploy.py) assume SSH access plus sudo; the script immediately asserts the architecture and aborts otherwise, so keep cross-device logic out of this repo.
- Idempotence matters: pyinfra restarts services only when `.changed` flags are set, so prefer `files.put(...).changed` and fact-driven conditionals over ad-hoc shell logic.
- Credentials in [inventory.py](inventory.py) are sample data; never commit real secrets and prefer environment-specific overrides when testing.

### Deployment Playbook Highlights
- Media stack: `files.download` unpacks mediamtx into `/opt/mediamtx`, syncs [configs/mediamtx.yml](configs/mediamtx.yml), and installs [configs/mediamtx.service](configs/mediamtx.service); any config tweak must include a matching systemd reload trigger.
- Serial/camera setup flips `/boot/firmware/config.txt` flags (disable auto detect, add `dtoverlay=imx708`, `dtoverlay=disable-bt`); when any of these mutations change, pyinfra runs `raspi-config` commands and schedules a reboot, so only touch that block if you expect downtime.
- MAVLink routing is provided by a downloaded static binary plus [configs/mavlink-router/main.conf](configs/mavlink-router/main.conf) and [configs/mavlink-router.service](configs/mavlink-router.service); remember the playbook restarts the service only when config/service files change.
- LTE prep checks for `wwan0`; if absent it sends `AT+CUSBPIDSWITCH` via `/dev/ttyUSB2`, then rewrites the NetworkManager `gsm` connection to force the hard-coded APN `mob.asm.net`. Treat these commands as the canonical way this repo provisions the SIM7600 HAT.
- Video storage: deployment auto-creates an ext4 partition labeled `boatpi-video` (if the disk has free space), leaves ~6 GB unallocated for the OS, mounts it at `/var/lib/boatpi-video`, and fstab+systemd ensure the mount exists before mediamtx starts.

### Streaming Stack Expectations
- [configs/mediamtx.yml](configs/mediamtx.yml) keeps almost the full upstream example but overrides key sections: WebRTC/HLS/RTSP are all on, ICE servers point at Google STUN, and the sole path `cam` uses `source: rpiCamera` with HDR enabled. Stick to these conventions so pyinfra copies the file verbatim.
- Low-latency viewing instructions in [README.md](README.md) rely on the `cam` path and ports 8554/8888/8889; update that doc if you change port mappings or add authentication.
- Systemd units under [configs/*.service](configs) are minimal (no `WantedBy` extras, run as root). If you add new daemons, follow the same pattern: stage the unit file in configs, push with `files.put`, and gate restarts on `daemon_reload` flags.
- mediamtx recordings write to `/var/lib/boatpi-video`, so keep that mount path consistent when extending configs; `mediamtx.service` uses `RequiresMountsFor` to delay startup until the partition is available.

### Telemetry & Networking
- [scripts/signal_monitor.py](scripts/signal_monitor.py) polls `nmcli` and `mmcli`, then emits MAVLink `NAMED_VALUE_FLOAT` metrics (`wifi_sig`, `lte_*`) over UDP via `pymavlink`; any change that adds metrics should remain under 10-char names to satisfy MAVLink constraints.
- The script runs inside `/opt/boatpi-signal/venv` managed by the playbook, and [configs/signal-monitor.service](configs/signal-monitor.service) wires it into `systemd` with dependencies on NetworkManager, ModemManager, and mavlink-router; keep those dependencies aligned when extending the service.
- Networking facts from `facts.hardware.NetworkDevices` and `facts.hardware.Ipv4Addrs` drive whether to send AT commands or rewrite NetworkManager profiles; reuse facts for additional conditional networking logic instead of shell greps.

### Contribution Tips
- When touching boot config or hardware-specific bits, document the rationale in [README.md](README.md) so operators understand new manual steps.
- Favor `server.shell` for short, deterministic command lists (as done for `raspi-config` and AT commands); wrap multi-command scripts in heredocs only if they need complex logic.
- Test pyinfra changes with `pyinfra inventory.py deploy.py --limit <host>` so you can validate a single Raspberry Pi before impacting all hosts.
- Keep dependencies lean: `pyproject.toml` only installs `pyinfra`, and runtime packages (mosh, python3-venv, pymavlink) are provisioned on-target—avoid adding dev-only libraries unless they are required for the deploy script itself.
