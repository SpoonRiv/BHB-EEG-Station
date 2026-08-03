#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import queue
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from configs.local_overrides import write_yaml_file_atomic
import core.ble.acquisition_process as acquisition_process
from core.ble.acquisition_process import _send_eeg_start_sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHANNEL_SELECTIONS = {
    8: {
        "n_channels": 8,
        "channel_names": ["P3", "PO4", "P7", "PO8", "PO7", "P8", "PO3", "P4"],
        "ref_channel_name": "Pz",
    },
    16: {
        "n_channels": 16,
        "channel_names": [
            "Fp1",
            "Fp2",
            "F3",
            "Fz",
            "F4",
            "T7",
            "C3",
            "Cz",
            "C4",
            "T8",
            "P3",
            "Pz",
            "P4",
            "O1",
            "Oz",
            "O2",
        ],
        "ref_channel_name": "CPz",
    },
}


def _create_isolated_config(temp_root: Path, n_channels: int) -> Path:
    """Copy only the tracked base config and seed an isolated local override."""
    config_dir = temp_root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    shutil.copy2(PROJECT_ROOT / "configs" / "config.yaml", config_path)
    shutil.copytree(PROJECT_ROOT / "configs" / "electrodes", config_dir / "electrodes")

    selection = CHANNEL_SELECTIONS[int(n_channels)]
    write_yaml_file_atomic(
        str(config_dir / "config.local.yaml"),
        {
            "eeg": dict(selection),
            "impedance": {"n_channels": int(n_channels)},
            "ui": {"channel_selection": dict(selection)},
        },
    )
    return config_path


class SendEegStartSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_stop_waits_then_starts(self) -> None:
        events = []

        async def send_cmd(command, action):
            events.append(("send", action, list(command)))

        async def sleep_fn(delay_sec):
            events.append(("sleep", delay_sec))

        await _send_eeg_start_sequence(
            send_cmd,
            [0x02, 0x02],
            [0x02, 0x01],
            sleep_fn=sleep_fn,
        )

        self.assertEqual(
            events,
            [
                ("send", "pre_stop_eeg", [0x02, 0x02]),
                ("sleep", 0.05),
                ("send", "start_eeg", [0x02, 0x01]),
            ],
        )

    async def test_pre_stop_failure_does_not_block_start(self) -> None:
        events = []

        async def send_cmd(command, action):
            events.append((action, list(command)))
            if action == "pre_stop_eeg":
                raise RuntimeError("device does not accept pre-stop")

        async def sleep_fn(delay_sec):
            events.append(("sleep", delay_sec))

        with self.assertLogs(level="WARNING") as captured_logs:
            await _send_eeg_start_sequence(
                send_cmd,
                [0x02, 0x02],
                [0x02, 0x01],
                sleep_fn=sleep_fn,
            )

        self.assertEqual(
            events,
            [
                ("pre_stop_eeg", [0x02, 0x02]),
                ("start_eeg", [0x02, 0x01]),
            ],
        )
        self.assertTrue(any("pre-stop failed" in line for line in captured_logs.output))

    async def test_start_failure_is_reported_to_caller(self) -> None:
        async def send_cmd(command, action):
            if action == "start_eeg":
                raise RuntimeError("start failed")

        async def sleep_fn(delay_sec):
            return None

        with self.assertRaisesRegex(RuntimeError, "start failed"):
            await _send_eeg_start_sequence(
                send_cmd,
                [0x02, 0x02],
                [0x02, 0x01],
                sleep_fn=sleep_fn,
            )


class AcquisitionStartIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_adc_command_pre_stops_before_start(self) -> None:
        stop_event = threading.Event()
        status_queue = queue.Queue()
        command_queue = queue.Queue()
        command_queue.put({"type": "start_mode", "mode": "eeg"})
        write_attempts = []

        class FakeOutlet:
            def __init__(self, cfg):
                self.cfg = cfg

            def push_samples(self, samples):
                return None

        class FakeClient:
            def __init__(self, address):
                self.address = address
                self.is_connected = True

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                self.is_connected = False
                return False

            async def start_notify(self, characteristic, callback):
                return None

            async def stop_notify(self, characteristic):
                return None

            async def write_gatt_char(self, characteristic, payload, response=False):
                raw = bytes(payload)
                write_attempts.append((raw, time.monotonic()))
                if raw == bytes((0x02, 0x01)):
                    stop_event.set()

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = _create_isolated_config(Path(temp_dir), n_channels=8)
            with patch.object(acquisition_process, "BleakClient", FakeClient), patch.object(
                acquisition_process, "LslOutletWriter", FakeOutlet
            ):
                await asyncio.wait_for(
                    acquisition_process._connect_and_stream(
                        str(config_path),
                        stop_event,
                        status_queue,
                        command_queue,
                        None,
                        "FAKE-ADDRESS",
                        "MSM008S02",
                    ),
                    timeout=2.0,
                )

        adc_attempts = [(payload, timestamp) for payload, timestamp in write_attempts if payload[:1] == b"\x02"]
        self.assertGreaterEqual(len(adc_attempts), 2)
        self.assertEqual(
            [payload for payload, _ in adc_attempts[:2]],
            [bytes((0x02, 0x02)), bytes((0x02, 0x01))],
        )
        self.assertGreaterEqual(adc_attempts[1][1] - adc_attempts[0][1], 0.04)

        statuses = []
        while True:
            try:
                statuses.append(status_queue.get_nowait())
            except queue.Empty:
                break
        self.assertTrue(
            any(item.get("type") == "mode_started" and item.get("mode") == "eeg" for item in statuses)
        )

    async def test_device_channel_mismatch_fails_before_ble_connection(self) -> None:
        stop_event = threading.Event()
        status_queue = queue.Queue()
        command_queue = queue.Queue()

        class ForbiddenClient:
            def __init__(self, address):
                raise AssertionError(f"BLE client must not be created for a channel mismatch: {address}")

        class ForbiddenOutlet:
            def __init__(self, cfg):
                raise AssertionError("LSL outlet must not be created for a channel mismatch")

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = _create_isolated_config(Path(temp_dir), n_channels=8)
            with patch.object(acquisition_process, "BleakClient", ForbiddenClient), patch.object(
                acquisition_process, "LslOutletWriter", ForbiddenOutlet
            ):
                await asyncio.wait_for(
                    acquisition_process._connect_and_stream(
                        str(config_path),
                        stop_event,
                        status_queue,
                        command_queue,
                        None,
                        "FAKE-ADDRESS",
                        "MSM016S00",
                    ),
                    timeout=1.0,
                )

        status = status_queue.get_nowait()
        self.assertEqual(status.get("type"), "error")
        self.assertEqual(status.get("code"), "eeg_channel_mode_mismatch")
        self.assertEqual(status.get("configured_eeg_channels"), 8)
        self.assertEqual(status.get("detected_eeg_channels"), 16)
        self.assertEqual(status.get("address"), "FAKE-ADDRESS")
        self.assertEqual(status.get("name"), "MSM016S00")
        self.assertEqual(status.get("module"), {"eeg_channels": 16, "stim_channels": 0})
        with self.assertRaises(queue.Empty):
            status_queue.get_nowait()
        self.assertTrue(command_queue.empty())


if __name__ == "__main__":
    unittest.main()
