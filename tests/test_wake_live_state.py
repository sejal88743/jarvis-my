import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main


class DummyUI:
    def __init__(self):
        self.state = None
        self.muted = False

    def set_state(self, state):
        self.state = state

    def write_log(self, *_args, **_kwargs):
        pass


class WakeLiveStateTests(unittest.TestCase):
    def setUp(self):
        self.ui = DummyUI()
        self.live = main.JarvisLive(self.ui)

    @patch.object(main, "wake_is_ready", return_value=True)
    @patch.object(main, "save_wake_word_enabled")
    def test_enabling_wake_word_keeps_live_mode(self, _save, _ready):
        self.live._wake_enabled = False
        self.live._awake = True

        result = self.live._ui_wake_toggle(True)

        self.assertEqual(result, "enabled")
        self.assertTrue(self.live._awake)
        self.assertTrue(self.live._wake_enabled)

    def test_ptt_release_keeps_listening_when_alive(self):
        self.live._wake_enabled = True
        self.live._awake = True

        self.live._on_ptt(False)

        self.assertEqual(self.ui.state, "LISTENING")

    def test_screen_tool_requires_protocol_liv_opt_in(self):
        self.assertFalse(self.live._protocol_liv_active)

        response = asyncio.run(self.live._execute_tool(SimpleNamespace(
            name="screen_process", args={}, id="test-call"
        )))

        self.assertIn("Protocol LIV is OFF", response.response["result"])


if __name__ == "__main__":
    unittest.main()
