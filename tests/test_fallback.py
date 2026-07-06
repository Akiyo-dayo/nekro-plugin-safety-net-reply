import unittest
from pathlib import Path
import sys

try:
    from nekro_plugin_safety_net_reply.fallback import (
        build_fallback_code,
        is_plain_text_fallback_candidate,
        sanitize_plain_text,
        split_message_text,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fallback import (  # type: ignore[no-redef]
        build_fallback_code,
        is_plain_text_fallback_candidate,
        sanitize_plain_text,
        split_message_text,
    )


class SafetyNetFallbackTests(unittest.TestCase):
    def test_detects_chinese_plain_text_that_is_not_python(self):
        text = "晨光透过窗帘的缝隙，在地板上切出一道明亮的金线。"

        self.assertTrue(is_plain_text_fallback_candidate(text, text))

    def test_does_not_rewrite_valid_tool_code(self):
        code = 'send_msg_text(_ck, "你好")'

        self.assertFalse(is_plain_text_fallback_candidate(code, code))

    def test_does_not_rewrite_malformed_python_like_tool_call(self):
        code = 'send_msg_text(_ck, "你好"'

        self.assertFalse(is_plain_text_fallback_candidate(code, code))

    def test_removes_think_block_before_sending(self):
        raw = "<think>内部推理</think>\n你好呀。"

        self.assertEqual(sanitize_plain_text(raw, raw), "你好呀。")

    def test_builds_na_style_msg_assignment(self):
        code = build_fallback_code('第一段\n\n他说："你好"')

        self.assertEqual(
            code,
            'msg = (\n'
            '    "第一段\\n\\n"\n'
            '    "他说：\\"你好\\""\n'
            ')\n\n'
            "send_plain_text_response(_ck, msg)",
        )

    def test_generated_code_executes_to_real_newlines(self):
        namespace = {"send_plain_text_response": lambda *_args: None, "_ck": "test"}

        exec(build_fallback_code("第一段\n\n第二段"), namespace)

        self.assertEqual(namespace["msg"], "第一段\n\n第二段")

    def test_splits_long_text_without_dropping_content(self):
        text = "甲" * 12 + "\n\n" + "乙" * 12 + "\n\n" + "丙" * 12

        chunks = split_message_text(text, max_chars=20)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        self.assertGreater(len(chunks), 1)


if __name__ == "__main__":
    unittest.main()
