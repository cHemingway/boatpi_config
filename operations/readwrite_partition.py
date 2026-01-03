"""Custom pyinfra operation(s) for provisioning read/write data partitions."""

from __future__ import annotations

import shlex
from typing import Dict, List, Tuple

import pyinfra.facts as facts
from pyinfra.api import operation
from pyinfra.api.exceptions import OperationError
from pyinfra.operations import files, server

from facts.readwrite_partition import DiskLayout, ParentDisk, PartitionByLabel

ALIGNMENT_BYTES = 1024 * 1024


def _gb_to_bytes(value: int) -> int:
    return value * 1024 * 1024 * 1024


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def _align_down(value: int, alignment: int) -> int:
    return (value // alignment) * alignment


def _plan_partition_bounds(free_segments: List[Dict[str, int]], reserve_gb: int, min_gb: int) -> Tuple[int, int]:
    if not free_segments:
        raise OperationError("No unallocated space remains for partition creation")

    reserve_bytes = _gb_to_bytes(reserve_gb)
    min_bytes = _gb_to_bytes(min_gb)
    candidate = free_segments[-1]
    usable_bytes = candidate["size"] - reserve_bytes

    if usable_bytes < min_bytes:
        raise OperationError("Insufficient free space to satisfy reserve + minimum requirements")

    start = _align_up(candidate["start"], ALIGNMENT_BYTES)
    end_limit = candidate["end"] - reserve_bytes
    end = _align_down(end_limit, ALIGNMENT_BYTES)

    if end <= start:
        raise OperationError("Computed invalid geometry for partition creation")

    return start, end


@operation()
def ensure_readwrite_partition(state, host, label, mount_point, reserve_gb, min_gb):
    """Ensure an ext4 read/write partition with *label* exists and is mounted at *mount_point*."""

    partition_path = host.get_fact(PartitionByLabel, label=label)

    mounts = host.get_fact(facts.server.Mounts) or {}
    root_mount = mounts.get("/")
    if not root_mount:
        raise OperationError("Unable to determine root filesystem information")

    root_device = root_mount.get("device")
    if not root_device:
        raise OperationError("Root filesystem device is unknown; cannot plan partition")

    resolved_root = host.get_fact(
        facts.server.Command,
        command=f"readlink -f {shlex.quote(root_device)}",
    )
    if resolved_root:
        root_device = resolved_root.strip()

    new_partition_path = None
    if not partition_path:
        parent_disk = host.get_fact(ParentDisk, device=root_device)
        if not parent_disk:
            raise OperationError(f"Unable to determine parent disk for {root_device}")

        disk_layout = host.get_fact(DiskLayout, disk=parent_disk)
        if not disk_layout:
            raise OperationError(f"Unable to inspect disk layout for {parent_disk}")

        start, end = _plan_partition_bounds(disk_layout["free"], reserve_gb, min_gb)
        next_partition = (max(disk_layout["partitions"]) if disk_layout["partitions"] else 0) + 1
        suffix = "p" if parent_disk[-1].isdigit() else ""
        new_partition_path = f"{parent_disk}{suffix}{next_partition}"

        mkpart_cmd = (
            f"parted -s {shlex.quote(parent_disk)} "
            f"mkpart {shlex.quote(label)} ext4 {start}B {end}B"
        )
        wait_cmd = (
            "bash -c \"for i in $(seq 1 10); do "
            f"[ -b {shlex.quote(new_partition_path)} ] && exit 0; "
            "sleep 1; done; exit 1\""
        )

        commands = [
            mkpart_cmd,
            f"partprobe {shlex.quote(parent_disk)} || true",
            "udevadm settle",
            wait_cmd,
            f"mkfs.ext4 -F -L {shlex.quote(label)} {shlex.quote(new_partition_path)}",
        ]

        yield server.shell(
            name="Create dedicated read/write partition",
            commands=commands,
            _sudo=True,
        )

        partition_path = new_partition_path

    fstab_line = f"LABEL={label} {mount_point} ext4 defaults,noatime 0 2"

    yield files.line(
        name=f"Ensure {mount_point} fstab entry",
        path="/etc/fstab",
        line=fstab_line,
        _sudo=True,
    )

    yield files.directory(
        name=f"Ensure {mount_point} directory",
        path=mount_point,
        mode="755",
        _sudo=True,
    )

    if partition_path:
        if mount_point not in mounts:
            yield server.shell(
                name="Mount read/write partition",
                commands=[f"mount {shlex.quote(mount_point)}"],
                _sudo=True,
            )
    else:
        raise OperationError(
            f"Partition with label {label} was not found or created; cannot mount {mount_point}"
        )
