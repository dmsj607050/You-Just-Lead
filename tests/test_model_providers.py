"""模型来源：多套配置、密钥存放、旧配置迁移。

这一层是**唯一碰密钥的地方**，所以这里测的是它的三条硬性质：

1. 密钥**永远不进 `settings.json`** —— 那个文件是可以拿给别人看的；
2. 多套能存、能切、能删，且「当前使用」不会指到一个不存在的 id 上；
3. 旧的单供应商配置（含那把密钥）能被一次性迁移过来，用户不用重填。

不发任何网络请求：`_keyring` 被换成内存里的假实现，`APPDATA` 指向临时目录，
所以既不会往真实凭据库写东西，也不会碰这台机器上真实的设置文件。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settings_service


class _FakeKeyring:
    """替掉 Windows 凭据管理器。"""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.store[(service, account)] = value


class _ProviderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.appdata = Path(self._temporary.name)

        env = patch.dict(os.environ, {"APPDATA": str(self.appdata)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        # 环境变量覆盖会盖住凭据管理器 —— 不排掉的话，"密钥从哪来"就测不准。
        for name in (settings_service.API_KEY_ENV, settings_service.LEGACY_API_KEY_ENV):
            os.environ.pop(name, None)

        self.keyring = _FakeKeyring()
        fake = patch.object(settings_service, "_keyring", return_value=self.keyring)
        fake.start()
        self.addCleanup(fake.stop)

    def settings_file(self) -> Path:
        return self.appdata / settings_service.APP_NAME / "settings.json"

    def add(self, **overrides):
        payload = {
            "name": "测试来源",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "sk-" + "x" * 20,
            "preset": "custom",
        }
        payload.update(overrides)
        return settings_service.upsert_provider(**payload)


class StorageTests(_ProviderTestCase):
    def test_a_key_never_lands_in_the_settings_file(self) -> None:
        self.add()
        text = self.settings_file().read_text(encoding="utf-8")
        payload = json.loads(text)

        self.assertNotIn("sk-", text, "密钥不该出现在配置文件里")
        self.assertNotIn("api_key", text)
        self.assertEqual(payload["settings_version"], settings_service.SETTINGS_VERSION)
        self.assertEqual(payload["providers"][0]["model"], "test-model")
        # 密钥应该只在凭据管理器里，账户名按来源区分。
        self.assertEqual(
            self.keyring.store[(settings_service.KEYRING_SERVICE, "provider:" + payload["providers"][0]["id"])],
            "sk-" + "x" * 20,
        )

    def test_the_status_view_never_carries_the_key(self) -> None:
        self.add()
        view = settings_service.providers_status()
        serialized = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("sk-", serialized)
        self.assertTrue(view["providers"][0]["has_key"], "只该回「有没有」，不回值")

    def test_several_providers_coexist_and_one_is_active(self) -> None:
        self.add(name="甲", preset="deepseek", base_url="https://api.deepseek.com", model="a")
        self.add(name="乙", preset="openai", base_url="https://api.openai.com/v1", model="b")
        status = settings_service.providers_status()

        self.assertEqual(len(status["providers"]), 2)
        self.assertEqual(status["active"], "deepseek", "新增到已存在的预设时沿用它自己的 id")

        switched = settings_service.set_active_provider("openai")
        self.assertEqual(switched["active"], "openai")
        self.assertEqual(switched["model"], "b")

    def test_deleting_the_active_provider_moves_the_pointer(self) -> None:
        self.add(name="甲", preset="deepseek", base_url="https://api.deepseek.com", model="a")
        self.add(name="乙", preset="openai", base_url="https://api.openai.com/v1", model="b")

        after = settings_service.delete_provider("openai")

        self.assertEqual([item["id"] for item in after["providers"]], ["deepseek"])
        self.assertEqual(after["active"], "deepseek", "删掉的正好是当前使用的那套时要换一个")

    def test_an_empty_key_leaves_the_stored_one_alone(self) -> None:
        first = self.add(model="old-model")
        provider_id = first["providers"][0]["id"]

        self.add(provider_id=provider_id, model="new-model", api_key="")
        _, _, model = settings_service.resolve_credentials()

        self.assertEqual(model, "new-model", "改模型不该要求重填密钥")
        self.assertTrue(settings_service.providers_status()["providers"][0]["has_key"])

    def test_the_base_url_must_look_like_a_url(self) -> None:
        with self.assertRaises(settings_service.SettingsError):
            self.add(base_url="api.deepseek.com")
        with self.assertRaises(settings_service.SettingsError):
            self.add(base_url="   ")
        with self.assertRaises(settings_service.SettingsError):
            self.add(name="")
        # 本地模型是 http，这不是错误。
        self.add(name="本地", base_url="http://127.0.0.1:11434/v1", preset="ollama")
        self.assertEqual(settings_service.providers_status()["active"], "ollama")

    def test_a_provider_that_needs_no_key_counts_as_configured(self) -> None:
        settings_service.upsert_provider(
            name="本地 Ollama",
            base_url="http://127.0.0.1:11434/v1",
            model="llama3.1",
            api_key="",
            preset="ollama",
        )
        status = settings_service.providers_status()

        self.assertTrue(status["configured"], "本地模型不需要密钥，不该被判成未配置")
        self.assertIsNone(status["key_source"])


class CredentialTests(_ProviderTestCase):
    def test_resolve_credentials_follows_the_active_provider(self) -> None:
        self.add(name="甲", preset="deepseek", base_url="https://api.deepseek.com", model="a", api_key="sk-" + "a" * 20)
        self.add(name="乙", preset="openai", base_url="https://api.openai.com/v1", model="b", api_key="sk-" + "b" * 20)
        settings_service.set_active_provider("openai")

        key, base_url, model = settings_service.resolve_credentials()

        self.assertEqual(base_url, "https://api.openai.com/v1")
        self.assertEqual(model, "b")
        self.assertEqual(key, "sk-" + "b" * 20)

    def test_the_environment_variable_overrides_the_stored_key(self) -> None:
        self.add(api_key="sk-" + "a" * 20)
        os.environ[settings_service.API_KEY_ENV] = "sk-from-environment"

        key, _, _ = settings_service.resolve_credentials()

        self.assertEqual(key, "sk-from-environment")
        self.assertEqual(settings_service.providers_status()["key_source"], "environment")

    def test_the_legacy_environment_variable_only_applies_to_deepseek(self) -> None:
        """旧名字只在当前这套是 DeepSeek 时认它 —— 多供应商之后它只对得上其中一家。"""
        self.add(preset="openai", base_url="https://api.openai.com/v1", model="b", api_key="sk-" + "b" * 20)
        os.environ[settings_service.LEGACY_API_KEY_ENV] = "sk-legacy"

        key, _, _ = settings_service.resolve_credentials()
        self.assertEqual(key, "sk-" + "b" * 20, "OpenAI 那套不该被 DeepSeek 的旧变量影响")

        settings_service.upsert_provider(
            name="甲", base_url="https://api.deepseek.com", model="a", api_key="sk-" + "a" * 20, preset="deepseek"
        )
        settings_service.set_active_provider("deepseek")
        key, _, _ = settings_service.resolve_credentials()
        self.assertEqual(key, "sk-legacy")

    def test_the_environment_variable_counts_as_a_stored_key(self) -> None:
        """没有系统凭据库的机器（纯环境变量配起来的 Linux）也要被认成「已配置」。

        这条钉的是一次真实部署：服务器上没有凭据库，`has_key` 只查凭据库，于是界面说
        「未配置」「缺密钥」，而 Agent 其实答得出来 —— 状态在说谎。
        """
        self.add(preset="deepseek", base_url="https://api.deepseek.com", model="a", api_key="")
        os.environ[settings_service.API_KEY_ENV] = "sk-from-environment"

        status = settings_service.providers_status()

        self.assertTrue(status["providers"][0]["has_key"])
        self.assertTrue(status["configured"])
        self.assertEqual(status["key_source"], "environment")

    def test_testing_the_active_provider_uses_the_environment_variable(self) -> None:
        """「测试连接」指定当前那套时，环境变量要生效。

        不给它生效，靠环境变量配起来的环境永远测不通 —— 用户会以为密钥填错了。
        """
        self.add(preset="deepseek", base_url="https://api.deepseek.com", model="a", api_key="")
        os.environ[settings_service.API_KEY_ENV] = "sk-from-environment"

        key, _, _ = settings_service.resolve_credentials("deepseek")
        self.assertEqual(key, "sk-from-environment")

    def test_the_environment_variable_never_reaches_another_provider(self) -> None:
        """环境变量是「当前那套」的覆盖，不是给每一套的。

        否则「测试某一套」会把当前这套的密钥发给另一个服务：既测不准，也是把密钥交出去。
        """
        self.add(name="甲", preset="deepseek", base_url="https://api.deepseek.com", model="a", api_key="")
        self.add(name="乙", preset="openai", base_url="https://api.openai.com/v1", model="b", api_key="")
        os.environ[settings_service.API_KEY_ENV] = "sk-from-environment"

        self.assertEqual(settings_service.resolve_credentials("deepseek")[0], "sk-from-environment")
        self.assertIsNone(settings_service.resolve_credentials("openai")[0], "非当前那套不该拿到环境变量")
        self.assertFalse(
            settings_service.providers_status()["providers"][1]["has_key"],
            "非当前的那套不能因为环境变量被说成「有密钥」",
        )


class MigrationTests(_ProviderTestCase):
    def test_the_legacy_single_provider_setup_migrates_once(self) -> None:
        """老版本只有一套 DeepSeek 配置：settings.json 里一个模型名，凭据库里一把密钥。"""
        legacy_dir = self.appdata / settings_service.APP_NAME
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "settings.json").write_text('{"deepseek_model": "deepseek-v4-pro"}', encoding="utf-8")
        self.keyring.store[(settings_service.KEYRING_SERVICE, settings_service.LEGACY_KEYRING_ACCOUNT)] = "sk-" + "z" * 20

        status = settings_service.providers_status()

        self.assertEqual(len(status["providers"]), 1)
        self.assertEqual(status["providers"][0]["preset"], "deepseek")
        self.assertEqual(status["providers"][0]["model"], "deepseek-v4-pro")
        self.assertTrue(status["providers"][0]["has_key"], "旧密钥要搬过来，不能让人重填")
        self.assertEqual(settings_service.resolve_credentials()[0], "sk-" + "z" * 20)

        # 迁移是**一次性**的：再读一次不会又添一套。
        self.assertEqual(len(settings_service.providers_status()["providers"]), 1)

    def test_nothing_configured_yet_is_not_an_error(self) -> None:
        status = settings_service.providers_status()

        self.assertEqual(status["providers"], [])
        self.assertEqual(status["active"], "")
        self.assertFalse(status["configured"])
        self.assertTrue(status["presets"], "预设始终要发出去，界面靠它引导第一次配置")
        with self.assertRaises(settings_service.SettingsError):
            settings_service.resolve_credentials()

    def test_a_corrupt_settings_file_says_so_instead_of_being_ignored(self) -> None:
        target = self.settings_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ not json", encoding="utf-8")

        with self.assertRaises(settings_service.SettingsError):
            settings_service.providers_status()


if __name__ == "__main__":
    unittest.main()
