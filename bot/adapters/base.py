"""
适配层公共类型。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, TypedDict


@dataclass(slots=True)
class ThreadSummary:
    thread_id: str
    cwd: str
    name: str
    preview: str
    created_at: int
    updated_at: int
    source: str
    status: str
    active_flags: list[str] = field(default_factory=list)
    path: str | None = None
    model_provider: str | None = None
    service_name: str | None = None

    @property
    def title(self) -> str:
        return self.name or self.preview or "（无标题）"


@dataclass(slots=True)
class ThreadSnapshot:
    summary: ThreadSummary
    turns: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeProfileSummary:
    name: str
    model_provider: str | None = None


@dataclass(slots=True)
class RuntimeModelSummary:
    model: str
    display_name: str | None = None
    is_default: bool = False
    hidden: bool = False


@dataclass(slots=True)
class RuntimeConfigSummary:
    current_profile: str | None = None
    current_model_provider: str | None = None
    profiles: list[RuntimeProfileSummary] = field(default_factory=list)


@dataclass(slots=True)
class SkillSummary:
    name: str
    description: str
    path: str
    scope: str
    enabled: bool
    short_description: str | None = None


@dataclass(slots=True)
class SkillLoadError:
    path: str
    message: str


@dataclass(slots=True)
class SkillsSnapshot:
    cwd: str
    skills: list[SkillSummary] = field(default_factory=list)
    errors: list[SkillLoadError] = field(default_factory=list)


@dataclass(slots=True)
class PluginSummary:
    plugin_id: str
    name: str
    marketplace_name: str
    marketplace_path: str | None
    installed: bool
    enabled: bool
    source_type: str
    availability: str
    install_policy: str
    auth_policy: str
    keywords: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PluginMarketplaceSummary:
    name: str
    path: str | None
    plugins: list[PluginSummary] = field(default_factory=list)


@dataclass(slots=True)
class PluginLoadError:
    marketplace_path: str
    message: str


@dataclass(slots=True)
class PluginCatalog:
    marketplaces: list[PluginMarketplaceSummary] = field(default_factory=list)
    marketplace_load_errors: list[PluginLoadError] = field(default_factory=list)
    featured_plugin_ids: list[str] = field(default_factory=list)

    def find_plugin(self, plugin_id: str) -> tuple[PluginMarketplaceSummary, PluginSummary] | None:
        normalized_plugin_id = str(plugin_id or "").strip()
        if not normalized_plugin_id:
            return None
        for marketplace in self.marketplaces:
            for plugin in marketplace.plugins:
                if plugin.plugin_id == normalized_plugin_id:
                    return marketplace, plugin
        return None


@dataclass(slots=True)
class PluginDetailSummary:
    plugin: PluginSummary
    description: str
    skill_names: list[str] = field(default_factory=list)
    hook_keys: list[str] = field(default_factory=list)
    app_names: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)


class TextTurnInputItem(TypedDict):
    type: Literal["text"]
    text: str


class LocalImageTurnInputItem(TypedDict):
    type: Literal["localImage"]
    path: str


TurnInputItem: TypeAlias = TextTurnInputItem | LocalImageTurnInputItem


class AgentAdapter(ABC):
    """Agent 适配器抽象接口。"""

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def create_thread(
        self,
        *,
        cwd: str,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
    ) -> ThreadSnapshot:
        ...

    @abstractmethod
    def resume_thread(
        self,
        thread_id: str,
        *,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
    ) -> ThreadSnapshot:
        ...

    @abstractmethod
    def list_threads(
        self,
        *,
        cwd: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        search_term: str | None = None,
        sort_key: str | None = None,
        source_kinds: list[str] | None = None,
        model_providers: list[str] | None = None,
    ) -> tuple[list[ThreadSummary], str | None]:
        ...

    @abstractmethod
    def read_thread(self, thread_id: str, *, include_turns: bool = False) -> ThreadSnapshot:
        ...

    @abstractmethod
    def read_runtime_config(self, *, cwd: str | None = None) -> RuntimeConfigSummary:
        ...

    @abstractmethod
    def list_models(self, *, include_hidden: bool = False) -> list[RuntimeModelSummary]:
        ...

    @abstractmethod
    def list_loaded_thread_ids(self) -> list[str]:
        ...

    @abstractmethod
    def set_active_profile(self, profile: str) -> RuntimeConfigSummary:
        ...

    @abstractmethod
    def set_thread_memory_mode(self, thread_id: str, *, mode: str) -> None:
        ...

    @abstractmethod
    def compact_thread(self, thread_id: str) -> None:
        ...

    @abstractmethod
    def list_skills(self, *, cwd: str, force_reload: bool = False) -> SkillsSnapshot:
        ...

    @abstractmethod
    def set_skill_enabled(self, *, skill_path: str = "", skill_name: str = "", enabled: bool) -> None:
        ...

    @abstractmethod
    def list_plugins(self, *, cwd: str | None = None) -> PluginCatalog:
        ...

    @abstractmethod
    def read_plugin(
        self,
        plugin_name: str,
        *,
        marketplace_name: str = "",
        marketplace_path: str | None = None,
    ) -> PluginDetailSummary:
        ...

    @abstractmethod
    def set_plugin_enabled(self, plugin_id: str, *, enabled: bool) -> None:
        ...

    @abstractmethod
    def rename_thread(self, thread_id: str, name: str) -> None:
        ...

    @abstractmethod
    def archive_thread(self, thread_id: str) -> None:
        ...

    @abstractmethod
    def start_turn(
        self,
        *,
        thread_id: str,
        input_items: list[TurnInputItem],
        cwd: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        profile: str | None = None,
        approval_policy: str | None = None,
        sandbox: str | None = None,
        reasoning_effort: str | None = None,
        collaboration_mode: str | None = None,
    ) -> dict[str, Any]:
        ...

    @abstractmethod
    def interrupt_turn(self, *, thread_id: str, turn_id: str) -> None:
        ...

    @abstractmethod
    def respond(self, request_id: int | str, *, result: dict | None = None, error: dict | None = None) -> None:
        ...
