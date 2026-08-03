#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import configs.local_overrides as local_overrides
import main as app_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_ATOMIC_WRITE = local_overrides.write_yaml_file_atomic
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


class BleConnectChannelAutoConfigTests(unittest.IsolatedAsyncioTestCase):
    def _prepare_config_tree(self, temp_root: Path, initial_mode: int) -> tuple[Path, Path, dict]:
        config_dir = temp_root / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.yaml"
        local_path = config_dir / "config.local.yaml"
        shutil.copy2(PROJECT_ROOT / "configs" / "config.yaml", config_path)
        shutil.copytree(PROJECT_ROOT / "configs" / "electrodes", config_dir / "electrodes")

        initial_selection = CHANNEL_SELECTIONS[int(initial_mode)]
        initial_raw = {
            "sentinel": {"keep": "top-level-value", "nested": {"answer": 42}},
            "eeg": {**initial_selection, "keep_eeg_key": "eeg-value"},
            "impedance": {"n_channels": int(initial_mode), "keep_impedance_key": "imp-value"},
            "ui": {
                "channel_selection": dict(initial_selection),
                "channel_presets_local": [
                    {
                        "name": "保留的本地预设",
                        "n_channels": 4,
                        "channel_names": ["L1", "L2", "L3", "L4"],
                        "ref_channel_name": "LR",
                    }
                ],
                "keep_ui_key": "ui-value",
            },
        }
        REAL_ATOMIC_WRITE(str(local_path), initial_raw)
        return config_path, local_path, initial_raw

    def _assert_runtime_channels(self, state: app_main.AppState, expected: dict) -> None:
        n_channels = int(expected["n_channels"])
        channel_names = list(expected["channel_names"])
        ref_channel_name = str(expected["ref_channel_name"])
        trigger_enabled = bool(state.config.eeg.lsl.include_trigger_channel)

        self.assertEqual(state.config.eeg.n_channels, n_channels)
        self.assertEqual(state.config.eeg.channel_names, channel_names)
        self.assertEqual(state.config.eeg.ref_channel_name, ref_channel_name)
        self.assertEqual(state.config.impedance.n_channels, n_channels)

        self.assertIs(state.controller.config, state.config)
        self.assertEqual(state.controller.config.eeg.n_channels, n_channels)
        self.assertEqual(state.controller.config.eeg.channel_names, channel_names)
        self.assertEqual(state.controller.config.eeg.ref_channel_name, ref_channel_name)
        self.assertEqual(state.controller.config.impedance.n_channels, n_channels)

        self.assertEqual(state.offline._base_channel_names, channel_names)
        self.assertEqual(state.offline._trigger_enabled, trigger_enabled)

        expected_total_channels = n_channels + (1 if trigger_enabled else 0)
        self.assertEqual(state.notch.cfg.channel_count, expected_total_channels)
        self.assertEqual(state.notch.cfg.has_trigger_channel, trigger_enabled)
        self.assertEqual(state.notch._channel_count, expected_total_channels)
        self.assertEqual(state.notch._n_filter_ch, n_channels)

        self.assertIsNotNone(state.psd_worker)
        assert state.psd_worker is not None
        self.assertEqual(state.psd_worker.channel_names, channel_names)
        self.assertEqual(state.psd_worker.n_channels, n_channels)
        self.assertEqual(state.psd_worker.has_trigger_channel, trigger_enabled)
        self.assertEqual(len(state.psd_worker._buf), n_channels)

    async def _assert_connect_auto_config(
        self,
        *,
        initial_mode: int,
        device_name: str,
        expected_mode: int,
    ) -> None:
        expected = CHANNEL_SELECTIONS[int(expected_mode)]

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir).resolve()
            config_path, local_path, initial_raw = self._prepare_config_tree(temp_root, initial_mode)
            write_paths = []

            def guarded_atomic_write(path, data):
                resolved_path = Path(path).resolve()
                try:
                    resolved_path.relative_to(temp_root)
                except ValueError as exc:
                    raise AssertionError(f"test attempted to write outside its temp tree: {resolved_path}") from exc
                write_paths.append(resolved_path)
                REAL_ATOMIC_WRITE(str(resolved_path), data)

            fake_main_path = temp_root / "main.py"
            with patch.object(app_main, "__file__", str(fake_main_path)), patch.object(
                app_main, "write_yaml_file_atomic", side_effect=guarded_atomic_write
            ), patch.object(
                local_overrides, "write_yaml_file_atomic", side_effect=guarded_atomic_write
            ):
                isolated_state = app_main.AppState()
                self.assertEqual(Path(isolated_state.config_path).resolve(), config_path.resolve())
                self.assertEqual(Path(isolated_state.local_override_path).resolve(), local_path.resolve())
                self.assertEqual(isolated_state.config.eeg.n_channels, initial_mode)

                def start_device(address, name):
                    self.assertEqual(address, "FAKE-ADDRESS")
                    self.assertEqual(name, device_name)
                    self._assert_runtime_channels(isolated_state, expected)
                    return True

                ensure_debug_forwarding = AsyncMock()
                with patch.object(app_main, "state", isolated_state), patch.object(
                    isolated_state.controller, "start_device", side_effect=start_device
                ) as start_device_mock, patch.object(
                    isolated_state, "ensure_debug_forwarding", new=ensure_debug_forwarding
                ):
                    response = await app_main.ble_connect(
                        app_main.BleConnectRequest(address="FAKE-ADDRESS", name=device_name)
                    )

                start_device_mock.assert_called_once_with("FAKE-ADDRESS", device_name)
                ensure_debug_forwarding.assert_awaited_once_with()

            self.assertEqual(response.get("status"), "success")
            self.assertIn("channel_config", response)
            channel_config = response["channel_config"]
            self.assertIsInstance(channel_config, dict)
            self.assertTrue(channel_config.get("auto_applied"))
            self.assertTrue(channel_config.get("changed"))
            self.assertEqual(channel_config.get("source"), "device_name_regex")
            self.assertEqual(channel_config.get("device_name"), device_name)
            self.assertEqual(channel_config.get("n_channels"), expected["n_channels"])
            self.assertEqual(channel_config.get("channel_names"), expected["channel_names"])
            self.assertEqual(channel_config.get("ref_channel_name"), expected["ref_channel_name"])

            self.assertEqual(write_paths, [local_path.resolve()])
            saved_raw = local_overrides.load_yaml_file(str(local_path))
            self.assertEqual(saved_raw["eeg"]["n_channels"], expected["n_channels"])
            self.assertEqual(saved_raw["eeg"]["channel_names"], expected["channel_names"])
            self.assertEqual(saved_raw["eeg"]["ref_channel_name"], expected["ref_channel_name"])
            self.assertEqual(saved_raw["impedance"]["n_channels"], expected["n_channels"])
            self.assertEqual(saved_raw["ui"]["channel_selection"], expected)

            self.assertEqual(saved_raw["sentinel"], initial_raw["sentinel"])
            self.assertEqual(saved_raw["eeg"]["keep_eeg_key"], initial_raw["eeg"]["keep_eeg_key"])
            self.assertEqual(
                saved_raw["impedance"]["keep_impedance_key"],
                initial_raw["impedance"]["keep_impedance_key"],
            )
            self.assertEqual(saved_raw["ui"]["keep_ui_key"], initial_raw["ui"]["keep_ui_key"])
            self.assertEqual(
                saved_raw["ui"]["channel_presets_local"],
                initial_raw["ui"]["channel_presets_local"],
            )

    async def test_msm008_switches_16_channel_runtime_to_8_before_start(self) -> None:
        await self._assert_connect_auto_config(
            initial_mode=16,
            device_name="MSM008S02",
            expected_mode=8,
        )

    async def test_msm016_switches_8_channel_runtime_to_16_before_start(self) -> None:
        await self._assert_connect_auto_config(
            initial_mode=8,
            device_name="MSM016S00",
            expected_mode=16,
        )


if __name__ == "__main__":
    unittest.main()
