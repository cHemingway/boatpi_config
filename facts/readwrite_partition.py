"""Facts related to read/write partition provisioning."""

from __future__ import annotations

import shlex

from pyinfra.api import FactBase


class PartitionByLabel(FactBase):
    """Return the device path for a filesystem label if it exists."""

    requires_command = "blkid"

    def command(self, label: str):  # type: ignore[override]
        quoted = shlex.quote(label)
        return f"blkid -L {quoted} 2>/dev/null || true"

    def process(self, output):  # type: ignore[override]
        if not output:
            return None
        first = str(output[0]).strip()
        return first or None


class ParentDisk(FactBase):
    """Return the parent block device for a partition path (e.g. /dev/mmcblk0p2 -> /dev/mmcblk0)."""

    requires_command = "lsblk"

    def command(self, device_path: str):  # type: ignore[override]
        quoted = shlex.quote(device_path)
        self._device = device_path
        return f"lsblk -no PKNAME {quoted}"

    def process(self, output):  # type: ignore[override]
        if not output:
            return None
        base = str(output[0]).strip()
        if not base:
            return None
        return f"/dev/{base}"


class DiskLayout(FactBase):
    """Return partition numbers and free segments for a disk using parted."""

    requires_command = "parted"
    requires_sudo = True

    def command(self, disk_path: str):  # type: ignore[override]
        quoted = shlex.quote(disk_path)
        self._disk = disk_path
        return f"parted -m {quoted} unit B print free"

    def process(self, output):  # type: ignore[override]
        partitions: list[int] = []
        free_segments: list[dict[str, int]] = []
        disk_line = getattr(self, "_disk", "")

        for raw in output or []:
            line = str(raw).strip()
            if not line or line.startswith("BYT") or (disk_line and line.startswith(disk_line)):
                continue

            line = line.rstrip(";")
            parts = line.split(":")
            if len(parts) < 4:
                continue

            if parts[-1] == "free":
                try:
                    free_segments.append(
                        {
                            "start": int(parts[1].rstrip("B")),
                            "end": int(parts[2].rstrip("B")),
                            "size": int(parts[3].rstrip("B")),
                        }
                    )
                except ValueError:
                    continue
            else:
                try:
                    partitions.append(int(parts[0]))
                except ValueError:
                    continue

        return {"partitions": partitions, "free": free_segments}
