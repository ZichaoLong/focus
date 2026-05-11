from __future__ import annotations

from dataclasses import dataclass

from bot.codex_config_reader import ResolvedProfileConfig
from bot.stores.thread_resume_profile_store import ThreadResumeProfileRecord


@dataclass(frozen=True, slots=True)
class ThreadResumeProfileSetting:
    profile: str
    model: str
    model_provider: str


def thread_resume_profile_setting_missing_fields(
    setting: ThreadResumeProfileSetting | None,
) -> tuple[str, ...]:
    if setting is None:
        return ()
    missing_fields: list[str] = []
    if not str(setting.profile or "").strip():
        missing_fields.append("profile")
    if not str(setting.model or "").strip():
        missing_fields.append("model")
    if not str(setting.model_provider or "").strip():
        missing_fields.append("model_provider")
    return tuple(missing_fields)


def thread_resume_profile_setting_is_concrete(setting: ThreadResumeProfileSetting | None) -> bool:
    return not thread_resume_profile_setting_missing_fields(setting)


def format_thread_resume_profile_missing_fields(missing_fields: tuple[str, ...]) -> str:
    return "、".join(f"`{field}`" for field in missing_fields)


def build_thread_resume_profile_setting(
    profile: str,
    *,
    model: str = "",
    model_provider: str = "",
    runtime_provider: str = "",
) -> ThreadResumeProfileSetting:
    normalized_profile = str(profile or "").strip()
    normalized_model = str(model or "").strip()
    normalized_model_provider = str(model_provider or runtime_provider or "").strip()
    return ThreadResumeProfileSetting(
        profile=normalized_profile,
        model=normalized_model,
        model_provider=normalized_model_provider,
    )


def resolve_thread_resume_profile_setting(
    profile: str,
    *,
    resolved: ResolvedProfileConfig,
    runtime_provider: str = "",
) -> ThreadResumeProfileSetting:
    return build_thread_resume_profile_setting(
        profile,
        model=resolved.model,
        model_provider=resolved.model_provider,
        runtime_provider=runtime_provider,
    )


def thread_resume_profile_setting_from_record(
    record: ThreadResumeProfileRecord | None,
) -> ThreadResumeProfileSetting | None:
    if record is None:
        return None
    normalized_profile = str(record.profile or "").strip()
    if not normalized_profile:
        return None
    return ThreadResumeProfileSetting(
        profile=normalized_profile,
        model=str(record.model or "").strip(),
        model_provider=str(record.model_provider or "").strip(),
    )


def thread_resume_profile_settings_equal(
    current_record: ThreadResumeProfileRecord | None,
    desired: ThreadResumeProfileSetting,
) -> bool:
    current = thread_resume_profile_setting_from_record(current_record)
    return current == desired


def describe_thread_resume_profile_setting_diff(
    current_record: ThreadResumeProfileRecord | None,
    desired: ThreadResumeProfileSetting,
) -> tuple[str, ...]:
    current = thread_resume_profile_setting_from_record(current_record)
    current_profile = _display_value(current.profile if current is not None else "")
    current_model = _display_value(current.model if current is not None else "")
    current_provider = _display_value(current.model_provider if current is not None else "")
    desired_profile = _display_value(desired.profile)
    desired_model = _display_value(desired.model)
    desired_provider = _display_value(desired.model_provider)
    diffs: list[str] = []
    if current is None or current.profile != desired.profile:
        diffs.append(f"profile：{current_profile} -> {desired_profile}")
    if current is None or current.model != desired.model:
        diffs.append(f"model：{current_model} -> {desired_model}")
    if current is None or current.model_provider != desired.model_provider:
        diffs.append(f"provider：{current_provider} -> {desired_provider}")
    return tuple(diffs)


def _display_value(value: str) -> str:
    normalized = str(value or "").strip()
    return f"`{normalized}`" if normalized else "`（未设置）`"
