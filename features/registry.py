"""Feature registry — Quan ly dang ky cac tinh nang cua bot.

File nay KHONG phu thuoc vao database. Giu nguyen tu phien ban truoc.
"""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Router


@dataclass
class FeatureInfo:
    """Thong tin ve mot tinh nang cua bot."""

    name: str
    description: str
    commands: list[str]
    router: Router


class FeatureRegistry:
    """Quan ly dang ky cac tinh nang cua bot."""

    _features: dict[str, FeatureInfo] = {}

    @classmethod
    def register(
        cls,
        name: str,
        description: str,
        commands: list[str],
        router: Router,
    ) -> None:
        """Dang ky mot tinh nang moi vao registry."""
        cls._features[name] = FeatureInfo(
            name=name,
            description=description,
            commands=commands,
            router=router,
        )

    @classmethod
    def get(cls, name: str) -> FeatureInfo | None:
        """Lay thong tin tinh nang theo ten."""
        return cls._features.get(name)

    @classmethod
    def get_all(cls) -> dict[str, FeatureInfo]:
        """Lay tat ca cac tinh nang da dang ky."""
        return dict(cls._features)

    @classmethod
    def get_all_commands(cls) -> list[dict]:
        """
        Lay danh sach tat ca cac lenh tu moi tinh nang.
        Tra ve list dict: {command, description, feature}.
        """
        commands = []
        for name, info in cls._features.items():
            for cmd in info.commands:
                commands.append({
                    "command": cmd,
                    "description": info.description,
                    "feature": name,
                })
        return commands
